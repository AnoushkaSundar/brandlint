"""Who may read a review. Engine ids reach the browser, so they prove nothing.

Findings quote the draft and masking previews show it in full, and creators include
outside agencies. The same rule as the content they belong to applies: a person who
can't open the piece gets a 404, so ids can't be used to probe for it.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.access import readable_content
from app.content.models import ContentVersion
from app.tenancy import scoped
from app.workflow.models import Review


def require_review(review_id: str, user: User, session: Session) -> None:
    content_id = session.scalar(
        scoped(session, ContentVersion, ContentVersion.content_id)
        .scoped_join(session, Review, Review.content_version_id == ContentVersion.id)
        .where(Review.engine_review_id == review_id)
    )
    # The lookup is inside the caller's org, so another org's review and a missing one
    # are the same answer, for every role.
    if content_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    readable_content(content_id, user, session)
