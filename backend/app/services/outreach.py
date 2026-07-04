"""Outreach core: add contact, render template, schedule, approve, send."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services import app_settings, audit, gmail, guards, scheduling

log = logging.getLogger("outreach")
_settings = get_settings()


_VAR_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def extract_variables(*texts: str) -> list[str]:
    """Unique {variable} names found across the given texts, in first-seen order."""
    seen: list[str] = []
    for t in texts:
        for name in _VAR_RE.findall(t or ""):
            if name not in seen:
                seen.append(name)
    return seen


def render(template_subject: str, template_body: str,
           values: dict[str, str]) -> tuple[str, str]:
    """Substitute {variable}s from `values`. A value that is missing or blank is
    treated as 'not provided': the whole line containing that placeholder is dropped,
    so optional fields (e.g. a Job ID line) vanish cleanly instead of leaving stubs.
    Genuinely unknown placeholders (not in `values` at all) are left intact."""
    filled = {k: v for k, v in values.items() if v is not None and str(v).strip()}
    blank = {k for k, v in values.items() if k not in filled}

    def sub(s: str) -> str:
        return _VAR_RE.sub(lambda m: filled.get(m.group(1), m.group(0)), s)

    def render_body(s: str) -> str:
        kept = [
            line for line in s.split("\n")
            if not any("{" + b + "}" in line for b in blank)
        ]
        return sub("\n".join(kept))

    # subject: substitute filled vars; blank ones just disappear (no line-dropping)
    subject = _VAR_RE.sub(
        lambda m: filled.get(m.group(1), "" if m.group(1) in blank else m.group(0)),
        template_subject,
    )
    return subject, render_body(template_body)


def add_contact(db: Session, *, name: str, company: str, email: str,
                template_id: int, variables: dict[str, str] | None = None,
                force: bool = False) -> dict:
    """Create recruiter + thread + an initial pending-approval send; return the send.

    `variables` fills any extra {placeholders} in the template (e.g. role, hr_name);
    recruiter_name and company are always derived from name/company below.
    """
    tmpl = db.execute(
        text("SELECT subject, body FROM templates WHERE id=:id AND is_active"),
        {"id": template_id},
    ).mappings().first()
    if not tmpl:
        raise ValueError(f"template {template_id} not found / inactive")

    name = name.strip() or "there"  # generic greeting when no contact name is given
    email = email.strip().lower()

    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError(f"'{email}' does not look like a valid email address")

    # never email an opted-out / bounced / dead address (hard stop, not overridable)
    reason = guards.is_suppressed(db, email)
    if reason:
        raise ValueError(
            f"{email} is on the suppression list ({reason}); remove it there first "
            f"if you really want to contact them again."
        )

    # per-person cooldown across threads; overridable with force=True
    if not force and guards.within_cooldown(db, email):
        raise ValueError(
            f"You emailed {email} within the last "
            f"{_settings.contact_cooldown_days} days. Re-add with force to override."
        )

    recruiter_id = db.execute(
        text(
            """
            INSERT INTO recruiters (name, company, email)
            VALUES (:name, :company, :email)
            ON CONFLICT (email) DO UPDATE SET name=EXCLUDED.name,
                                              company=EXCLUDED.company
            RETURNING id
            """
        ),
        {"name": name, "company": company, "email": email},
    ).scalar_one()

    # refuse a second live thread with the same recruiter so we never double-email
    existing = db.execute(
        text(
            """
            SELECT id FROM threads
            WHERE recruiter_id = :rid
              AND status IN ('active','replied_unlabeled','replied_positive')
            LIMIT 1
            """
        ),
        {"rid": recruiter_id},
    ).first()
    if existing:
        raise ValueError(
            f"You already have an open thread with {email}. "
            f"Cancel or close it before adding again."
        )

    thread_id = db.execute(
        text(
            """
            INSERT INTO threads (recruiter_id, template_id, status)
            VALUES (:rid, :tid, 'active') RETURNING id
            """
        ),
        {"rid": recruiter_id, "tid": template_id},
    ).scalar_one()

    # name/company/signature are canonical built-ins ({recruiter_name} kept as an
    # alias for backward compatibility); extra per-send vars fill the rest
    values = {**(variables or {}), "name": name, "recruiter_name": name,
              "company": company, "signature": app_settings.get().signature}
    subject, body = render(tmpl["subject"], tmpl["body"], values)
    scheduled_at = scheduling.compute_send_time()

    send = db.execute(
        text(
            """
            INSERT INTO sends (thread_id, type, subject, body, scheduled_at, status)
            VALUES (:tid, 'initial', :subject, :body, :sched, 'pending_approval')
            RETURNING id, thread_id, type, subject, body, scheduled_at, sent_at,
                      status, error
            """
        ),
        {"tid": thread_id, "subject": subject, "body": body, "sched": scheduled_at},
    ).mappings().first()
    db.commit()
    return dict(send)


def approve_send(db: Session, send_id: int) -> None:
    """Flip a pending send to approved so the scheduler will dispatch it."""
    res = db.execute(
        text("UPDATE sends SET status='approved' "
             "WHERE id=:id AND status='pending_approval'"),
        {"id": send_id},
    )
    if res.rowcount == 0:
        raise ValueError(f"send {send_id} not found or not pending_approval")
    audit.record(db, "send.approve", entity="send", entity_id=send_id)
    db.commit()


def unapprove_send(db: Session, send_id: int) -> dict:
    """Send an approved-but-unsent draft back for review so it can be edited.

    Re-approval is required afterwards — editing never bypasses human review.
    """
    row = db.execute(
        text("UPDATE sends SET status='pending_approval' "
             "WHERE id=:id AND status='approved' "
             "RETURNING id, thread_id, type, subject, body, scheduled_at, sent_at, "
             "status, error, attempts, gmail_message_id"),
        {"id": send_id},
    ).mappings().first()
    if not row:
        raise ValueError(f"send {send_id} not found or not approved")
    audit.record(db, "send.unapprove", entity="send", entity_id=send_id)
    db.commit()
    return dict(row)


def edit_send(db: Session, send_id: int, *, subject: str | None = None,
              body: str | None = None, scheduled_at=None) -> dict:
    """Edit a still-pending draft's subject/body/scheduled time before approval;
    return the send. scheduled_at is never recomputed automatically (e.g. by
    approving/unapproving, or by a later Settings change) — this is the only way
    to correct a draft's send time once it's been queued under stale settings."""
    row = db.execute(
        text("SELECT status FROM sends WHERE id=:id"), {"id": send_id}
    ).first()
    if not row:
        raise ValueError(f"send {send_id} not found")
    if row[0] != "pending_approval":
        raise ValueError("only a pending draft can be edited")
    sets, params = [], {"id": send_id}
    if subject is not None:
        if not subject.strip():
            raise ValueError("subject cannot be empty")
        sets.append("subject=:subject")
        params["subject"] = subject
    if body is not None:
        if not body.strip():
            raise ValueError("body cannot be empty")
        sets.append("body=:body")
        params["body"] = body
    if scheduled_at is not None:
        sets.append("scheduled_at=:scheduled_at")
        params["scheduled_at"] = scheduled_at
    if not sets:
        raise ValueError("nothing to update")
    # re-assert pending in the WHERE clause so a concurrent approve/claim can't be
    # overwritten between the read above and this update
    updated = db.execute(
        text(f"UPDATE sends SET {', '.join(sets)} "
             "WHERE id=:id AND status='pending_approval' "
             "RETURNING id, thread_id, type, subject, body, scheduled_at, sent_at, "
             "status, error, attempts, gmail_message_id"),
        params,
    ).mappings().first()
    if updated is None:
        raise ValueError("draft was approved or changed; reload and try again")
    db.commit()
    return dict(updated)


def cancel_send(db: Session, send_id: int) -> None:
    """Cancel a not-yet-sent send."""
    res = db.execute(
        text("UPDATE sends SET status='cancelled' WHERE id=:id AND status IN "
             "('pending_approval','approved')"),
        {"id": send_id},
    )
    if res.rowcount:
        audit.record(db, "send.cancel", entity="send", entity_id=send_id)
    db.commit()


def close_thread(db: Session, thread_id: int) -> None:
    """Abandon a thread: mark 'dead', cancel unsent mail, free the recruiter to re-add."""
    res = db.execute(
        text("SELECT status FROM threads WHERE id=:id"), {"id": thread_id}
    ).first()
    if not res:
        raise ValueError(f"thread {thread_id} not found")
    if res[0] == "dead":
        return  # idempotent
    db.execute(
        text("UPDATE sends SET status='cancelled' WHERE thread_id=:tid "
             "AND status IN ('pending_approval','approved')"),
        {"tid": thread_id},
    )
    db.execute(
        text("UPDATE threads SET status='dead', updated_at=now() WHERE id=:tid"),
        {"tid": thread_id},
    )
    audit.record(db, "thread.close", entity="thread", entity_id=thread_id)
    db.commit()


def reschedule_missed() -> int:
    """Startup catch-up: recover orphaned sends and roll past-due ones forward."""
    db = SessionLocal()
    try:
        db.execute(text("UPDATE sends SET status='approved' WHERE status='sending'"))
        rows = db.execute(
            text("SELECT id, scheduled_at FROM sends "
                 "WHERE status='approved' AND scheduled_at < now()")
        ).mappings().all()
        for r in rows:
            new_time = scheduling.reschedule_if_past(r["scheduled_at"])
            db.execute(
                text("UPDATE sends SET scheduled_at=:t WHERE id=:id"),
                {"t": new_time, "id": r["id"]},
            )
        db.commit()
        return len(rows)
    finally:
        db.close()


_MAX_SENDS_PER_TICK = 2   # cap the batch to avoid a burst when a backlog builds
_STALE_AFTER_MINUTES = 30  # past this, roll to the next window instead of firing late
_SENDING_ORPHAN_MINUTES = 10  # 'sending' older than this = crashed mid-send, recover it
_RETRYABLE_HINTS = ("rate", "quota", "timeout", "timed out", "temporarily",
                    "503", "500", "502", "504", "connection", "unavailable")


def _log_event(db: Session, send_id: int, event: str, detail: str | None = None) -> None:
    """Append an audit row for a send attempt."""
    db.execute(
        text("INSERT INTO send_events (send_id, event, detail) VALUES (:sid, :ev, :d)"),
        {"sid": send_id, "ev": event, "d": (detail or "")[:500] or None},
    )


def _is_retryable(err: Exception) -> bool:
    """True for transient errors (rate limit / 5xx / network) worth retrying."""
    return any(h in str(err).lower() for h in _RETRYABLE_HINTS)


def process_due_sends() -> None:
    """Send due emails: cap-limited, lock-claimed, guarded, retried on the next tick."""
    db = SessionLocal()
    try:
        # recover crashed-mid-send rows, but never one a concurrent worker is sending
        db.execute(
            text("UPDATE sends SET status='approved' WHERE status='sending' "
                 "AND updated_at < now() - make_interval(mins => :m)"),
            {"m": _SENDING_ORPHAN_MINUTES},
        )
        db.commit()

        remaining = guards.daily_cap_remaining(db)
        if remaining <= 0:
            log.info("daily send cap reached; skipping this tick")
            return
        batch_lim = min(_MAX_SENDS_PER_TICK, remaining)

        # SKIP LOCKED makes concurrent ticks/instances grab disjoint rows
        due = db.execute(
            text(
                """
                SELECT s.id, s.thread_id, s.type, s.subject, s.body, s.scheduled_at,
                       s.attempts, r.email, t.gmail_thread_id, tm.attach_resume
                FROM sends s
                JOIN threads t ON t.id = s.thread_id
                JOIN recruiters r ON r.id = t.recruiter_id
                JOIN templates tm ON tm.id = t.template_id
                WHERE s.status='approved' AND s.scheduled_at <= now()
                ORDER BY s.scheduled_at
                LIMIT :lim
                FOR UPDATE OF s SKIP LOCKED
                """
            ),
            {"lim": batch_lim},
        ).mappings().all()

        # claim under lock (flip to 'sending'), then commit to release before network I/O
        claimed = []
        for row in due:
            age_min = (
                scheduling.now_tz()
                - scheduling.to_local(row["scheduled_at"])
            ).total_seconds() / 60
            if age_min > _STALE_AFTER_MINUTES:
                # roll forward (preserves a follow-up's return-date intent vs. firing late)
                new_time = scheduling.reschedule_if_past(row["scheduled_at"])
                db.execute(
                    text("UPDATE sends SET scheduled_at=:t, updated_at=now() WHERE id=:id"),
                    {"t": new_time, "id": row["id"]},
                )
                log.info("send_id=%s stale (%.0fmin) -> rescheduled to %s",
                         row["id"], age_min, new_time)
                continue
            db.execute(
                text("UPDATE sends SET status='sending', updated_at=now() WHERE id=:id"),
                {"id": row["id"]},
            )
            claimed.append(row)
        db.commit()

        for row in claimed:
            skip = _presend_skip_reason(db, row)
            if skip:
                db.execute(
                    text("UPDATE sends SET status='cancelled', updated_at=now() WHERE id=:id"),
                    {"id": row["id"]},
                )
                _log_event(db, row["id"], "skipped", skip)
                db.commit()
                log.info("send_id=%s skipped: %s", row["id"], skip)
                continue
            _dispatch_one(db, row)
    finally:
        db.close()


def _presend_skip_reason(db: Session, row) -> str | None:
    """Why this claimed send must not go out now (reply/bounce/suppression), or None."""
    status = db.execute(
        text("SELECT status FROM threads WHERE id=:tid"), {"tid": row["thread_id"]}
    ).scalar_one_or_none()
    if status is None:
        return "thread missing"
    if status == "bounced":
        return "thread bounced"
    if status not in ("active", "ooo"):  # a reply moved it out of the sendable states
        return "reply arrived before send"
    if guards.is_suppressed(db, row["email"]):
        return "address suppressed"
    return None


def _dispatch_one(db: Session, row) -> None:
    """Send one claimed row; on transient failure retry on a later tick, else fail."""
    attempts = (row["attempts"] or 0) + 1
    _log_event(db, row["id"], "attempt", f"#{attempts}")
    db.commit()
    try:
        resp = gmail.send_email(
            to=row["email"],
            subject=row["subject"],
            body=row["body"],
            # attachment is a per-template choice (job application yes, sales intro no)
            attachment_path=_settings.resume_path if row["attach_resume"] else None,
            thread_id=row["gmail_thread_id"],
        )
        db.execute(
            text("UPDATE sends SET status='sent', sent_at=now(), error=NULL, "
                 "attempts=:a, gmail_message_id=:mid, updated_at=now() WHERE id=:id"),
            {"a": attempts, "mid": resp.get("id"), "id": row["id"]},
        )
        # capture the gmail thread id on first send so replies can be polled
        if not row["gmail_thread_id"]:
            db.execute(
                text("UPDATE threads SET gmail_thread_id=:gt, updated_at=now() WHERE id=:tid"),
                {"gt": resp.get("threadId"), "tid": row["thread_id"]},
            )
        db.execute(
            text("UPDATE recruiters SET last_contacted_at=now() WHERE id=("
                 "SELECT recruiter_id FROM threads WHERE id=:tid)"),
            {"tid": row["thread_id"]},
        )
        _log_event(db, row["id"], "sent", resp.get("id"))
        db.commit()
        log.info("sent send_id=%s to %s (attempt %d)", row["id"], row["email"], attempts)
    except Exception as e:  # noqa: BLE001 — record and decide retry-later vs. fail
        db.rollback()
        if _is_retryable(e) and attempts < _settings.max_send_attempts:
            # back to 'approved' with a short delay; a later tick retries (no sleep here)
            delay_s = min(60 * attempts, 300)
            retry_at = scheduling.now_ist() + timedelta(seconds=delay_s)
            db.execute(
                text("UPDATE sends SET status='approved', attempts=:a, error=:err, "
                     "scheduled_at=:t, updated_at=now() WHERE id=:id"),
                {"a": attempts, "err": str(e)[:500], "t": retry_at, "id": row["id"]},
            )
            _log_event(db, row["id"], "retry", f"in {delay_s}s: {e}")
            db.commit()
            log.warning("send_id=%s transient error, retry ~%ds: %s", row["id"], delay_s, e)
        else:
            db.execute(
                text("UPDATE sends SET status='failed', attempts=:a, error=:err, "
                     "updated_at=now() WHERE id=:id"),
                {"a": attempts, "err": str(e)[:500], "id": row["id"]},
            )
            _log_event(db, row["id"], "failed", str(e))
            db.commit()
            log.error("send_id=%s failed permanently: %s", row["id"], e)
