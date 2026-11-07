"""Who may read a review. Engine ids reach the browser, so they prove nothing.

Findings quote the draft and masking previews show it in full, and creators include
outside agencies. The same rule as the content they belong to applies: a person who
can't open the piece gets a 404, so ids can't be used to probe for it.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.access import readable_content
from app.content.models import ContentVersion
from app.contracts import Role
from app.workflow.models import Review


def require_review(review_id: str, user: User, session: Session) -> None:
    content_id = session.scalar(
        select(ContentVersion.content_id)
        .join(Review, Review.content_version_id == ContentVersion.id)
        .where(Review.engine_review_id == review_id)
    )
    if content_id is not None:
        readable_content(content_id, user, session)
    elif user.role == Role.creator.value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
