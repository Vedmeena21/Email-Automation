"""Dashboard stats / counts for the overview and nav badges."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db

router = APIRouter(tags=["stats"])


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    send_counts = dict(
        db.execute(
            text("SELECT status, count(*) FROM sends GROUP BY status")
        ).all()
    )
    thread_counts = dict(
        db.execute(
            text("SELECT status, count(*) FROM threads GROUP BY status")
        ).all()
    )
    # A thread only counts as "awaiting reply" if its most recent send actually
    # went out — one whose latest send permanently failed never reached anyone,
    # so it belongs in its own failed bucket, not lumped in with real sent mail.
    active_awaiting = db.execute(
        text(
            """
            SELECT count(*) FROM threads t
            JOIN LATERAL (
                SELECT status FROM sends s WHERE s.thread_id = t.id
                ORDER BY s.id DESC LIMIT 1
            ) ls ON true
            WHERE t.status = 'active' AND ls.status = 'sent'
            """
        )
    ).scalar()
    sent_total = send_counts.get("sent", 0)
    replied = (
        thread_counts.get("replied_unlabeled", 0)
        + thread_counts.get("replied_positive", 0)
        + thread_counts.get("replied_negative", 0)
        + thread_counts.get("ooo", 0)
    )
    reply_rate = round(replied / sent_total * 100) if sent_total else 0

    return {
        "pending_approval": send_counts.get("pending_approval", 0),
        "scheduled": send_counts.get("approved", 0),
        "sent": sent_total,
        "failed": send_counts.get("failed", 0),
        "needs_review": thread_counts.get("replied_unlabeled", 0),
        "positive": thread_counts.get("replied_positive", 0),
        "negative": thread_counts.get("replied_negative", 0),
        "ooo": thread_counts.get("ooo", 0),
        "active": active_awaiting,
        "reply_rate": reply_rate,
    }
