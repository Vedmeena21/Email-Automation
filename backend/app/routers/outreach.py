"""Contact / send / thread endpoints (the dashboard's main surface)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.schemas import ContactCreate, SendEdit, SendOut, ThreadOut
from app.services import outreach

router = APIRouter(tags=["outreach"])


@router.post("/contacts", response_model=SendOut, status_code=201)
def add_contact(payload: ContactCreate, db: Session = Depends(get_db)):
    """Add a recruiter, render their template, schedule a pending-approval send."""
    try:
        send = outreach.add_contact(
            db, name=payload.name, company=payload.company,
            email=payload.email, template_id=payload.template_id,
            variables=payload.variables, force=payload.force,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return send


@router.patch("/sends/{send_id}", response_model=SendOut)
def edit_send(send_id: int, payload: SendEdit, db: Session = Depends(get_db)):
    """Edit a pending draft's subject/body/scheduled time before approving it."""
    try:
        return outreach.edit_send(
            db, send_id, subject=payload.subject, body=payload.body,
            scheduled_at=payload.scheduled_at,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/sends/{send_id}/unapprove", response_model=SendOut)
def unapprove(send_id: int, db: Session = Depends(get_db)):
    """Pull an approved-but-unsent draft back to pending so it can be edited."""
    try:
        return outreach.unapprove_send(db, send_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/sends/{send_id}/approve", status_code=204)
def approve(send_id: int, db: Session = Depends(get_db)):
    try:
        outreach.approve_send(db, send_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/sends/{send_id}/cancel", status_code=204)
def cancel(send_id: int, db: Session = Depends(get_db)):
    outreach.cancel_send(db, send_id)


@router.post("/threads/{thread_id}/close", status_code=204)
def close_thread(thread_id: int, db: Session = Depends(get_db)):
    """Abandon a thread: mark it dead and cancel any unsent emails."""
    try:
        outreach.close_thread(db, thread_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/sends", response_model=list[SendOut])
def list_sends(status: str | None = None,
               limit: int = Query(default=500, ge=1, le=2000),
               db: Session = Depends(get_db)):
    q = "SELECT * FROM sends"
    params: dict = {"lim": limit}
    if status:
        q += " WHERE status=:status"
        params["status"] = status
    q += " ORDER BY scheduled_at NULLS LAST, id DESC LIMIT :lim"
    rows = db.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/threads", response_model=list[ThreadOut])
def list_threads(status: str | None = None,
                 search: str | None = Query(default=None, max_length=200),
                 limit: int = Query(default=500, ge=1, le=2000),
                 db: Session = Depends(get_db)):
    """Threads joined with recruiter + their latest send (for dashboard sections).

    One query via a LATERAL join for the latest send per thread — avoids the N+1
    round-trips that would hammer the pooled Postgres as the pipeline grows.
    `search` matches the recruiter's name/company/email via the generated
    tsvector column (see migration 006); `websearch_to_tsquery` accepts plain
    typed-in phrases without the caller needing tsquery syntax.
    """
    sql = """
        SELECT t.id, t.recruiter_id, r.name AS recruiter_name, r.company, r.email,
               t.template_id, t.status, t.gmail_thread_id, t.ooo_return_date,
               t.created_at,
               ls.id AS ls_id, ls.thread_id AS ls_thread_id, ls.type AS ls_type,
               ls.subject AS ls_subject, ls.body AS ls_body,
               ls.scheduled_at AS ls_scheduled_at, ls.sent_at AS ls_sent_at,
               ls.status AS ls_status, ls.error AS ls_error
        FROM threads t
        JOIN recruiters r ON r.id = t.recruiter_id
        LEFT JOIN LATERAL (
            SELECT * FROM sends s WHERE s.thread_id = t.id
            ORDER BY s.id DESC LIMIT 1
        ) ls ON true
    """
    conditions, params = [], {"lim": limit}
    if status:
        conditions.append("t.status=:status")
        params["status"] = status
    if search and search.strip():
        conditions.append("r.search_vector @@ websearch_to_tsquery('simple', :search)")
        params["search"] = search.strip()
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY t.created_at DESC LIMIT :lim"
    rows = db.execute(text(sql), params).mappings().all()

    out = []
    for row in rows:
        d = {k: v for k, v in row.items() if not k.startswith("ls_")}
        d["latest_send"] = (
            {
                "id": row["ls_id"],
                "thread_id": row["ls_thread_id"],
                "type": row["ls_type"],
                "subject": row["ls_subject"],
                "body": row["ls_body"],
                "scheduled_at": row["ls_scheduled_at"],
                "sent_at": row["ls_sent_at"],
                "status": row["ls_status"],
                "error": row["ls_error"],
            }
            if row["ls_id"] is not None
            else None
        )
        out.append(d)
    return out
