"""Re-review requests: an admin asks for pieces citing a changed fact to be checked again.

A request is an audit row, so it's recorded with who asked and when. It's pending until
the piece's next review starts, and it never changes a piece's state by itself.
"""

from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.admin.rulebook import current_rulebook_version
from app.auth.models import User
from app.tenancy import scoped
from app.workflow.models import AuditLog, Review

ACTION = "content:rereview_requested"


class RereviewOut(BaseModel):
    fact_id: str
    requested_at: datetime


def queue(
    session: Session, fact_id: str, content_ids: Iterable[str], actor: User
) -> list[str]:
    """Records a request for each piece. The caller commits."""
    queued = list(dict.fromkeys(content_ids))
    version = current_rulebook_version(session)
    for content_id in queued:
        session.add(
            AuditLog(
                actor_id=actor.id,
                role=actor.role,
                action=ACTION,
                target_type="content",
                target_id=content_id,
                before=None,
                after={"fact_id": fact_id},
                rulebook_version=version,
            )
        )
    session.flush()
    return queued


def pending(
    session: Session, content_id: str, latest_review: Review | None
) -> RereviewOut | None:
    """The newest request made since the piece's latest review started, if any."""
    query = (
        scoped(session, AuditLog)
        .where(
            AuditLog.action == ACTION,
            AuditLog.target_type == "content",
            AuditLog.target_id == content_id,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    if latest_review is not None:
        query = query.where(AuditLog.created_at > latest_review.created_at)
    row = session.scalar(query)
    if row is None:
        return None
    return RereviewOut(
        fact_id=str((row.after or {}).get("fact_id", "")),
        requested_at=row.created_at,
    )
