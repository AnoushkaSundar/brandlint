from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.models import Content, ContentVersion
from app.contracts import ContentState, Role
from app.workflow.models import Review


def can_read(user: User, content: Content) -> bool:
    return user.role != Role.creator.value or content.creator_id == user.id


def readable_content(content_id: str, user: User, session: Session) -> Content:
    content = session.get(Content, content_id)
    # Not found rather than forbidden, so ids can't be used to probe for content.
    if content is None or not can_read(user, content):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Content not found")
    return content


def latest_review(session: Session, content_id: str) -> Review | None:
    return session.scalar(
        select(Review)
        .join(ContentVersion, Review.content_version_id == ContentVersion.id)
        .where(ContentVersion.content_id == content_id)
        .order_by(Review.created_at.desc())
        .limit(1)
    )


RESTARTABLE_RUNS = ("failed", "unknown")


def can_start_again(state: str, run_status: str) -> bool:
    """A run in AI review can be started again only if it ended without finishing.

    A finished run is waiting to move on, and a running one is still going, so either
    would repeat a paid review.
    """
    return state == ContentState.ai_review.value and run_status in RESTARTABLE_RUNS
