"""Adding a version to a piece of content and starting its review.

Shared by the content routes and the CI integration, so a CI run goes through exactly the
review path a creator's upload does: the same checks, limits, rulebook and engine.
"""

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.admin.rulebook import RulebookNotFound, current_rulebook_version, rulebook_at
from app.auth.models import User
from app.clients import engine as engine_client
from app.content import rereview, storage
from app.content.access import can_start_again, latest_review
from app.content.models import Content, ContentVersion
from app.contracts import ContentSource, ContentState
from app.gateway import budget
from app.gateway.budget import BudgetExceeded
from app.tenancy import limits, scoped
from app.workflow.models import Review
from app.workflow.transitions import move_content

REVIEWABLE_STATES = {
    ContentState.draft.value,
    ContentState.ai_review.value,
    ContentState.resolving.value,
}


def add_version(
    session: Session,
    content: Content,
    user: User,
    text: str,
    upload: storage.CheckedUpload | None,
    file_name: str | None,
) -> ContentVersion:
    latest = session.scalar(
        scoped(session, ContentVersion, func.max(ContentVersion.version)).where(
            ContentVersion.content_id == content.id
        )
    )
    version = ContentVersion(
        content_id=content.id,
        version=(latest or 0) + 1,
        text=text,
        created_by=user.id,
    )
    session.add(version)
    session.flush()
    if upload is not None:
        version.file_ref = storage.save_upload(user.org_id, version.id, upload)
        version.file_name = file_name
    return version


def versions(session: Session, content_id: str) -> list[ContentVersion]:
    return list(
        session.scalars(
            scoped(session, ContentVersion)
            .where(ContentVersion.content_id == content_id)
            .order_by(ContentVersion.version.desc())
        )
    )


def content_source(content: Content, version: ContentVersion) -> ContentSource:
    """What the engine reviews. A lost file is refused before anything changes."""
    file_bytes = None
    if version.file_ref:
        try:
            file_bytes = storage.stored_path(version.file_ref).read_bytes()
        except OSError:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The uploaded file is missing. Upload it again to start a review.",
            ) from None
    return ContentSource(
        data_class=content.data_class,
        text=version.text,
        file_name=version.file_name,
        file_bytes=file_bytes,
    )


def begin_review(session: Session, content: Content, user: User) -> Review:
    """Starts a review of the content's latest version. The state checks, limits and the
    empty-rulebook check are the ones a creator hits; the caller gets the HTTP error."""
    content_id = content.id
    if content.state not in REVIEWABLE_STATES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This content can't be reviewed in its current state.",
        )
    latest = versions(session, content_id)[0]
    previous = latest_review(session, content_id)
    # Reviewing the same text against the same rules would only wipe the decisions.
    # A new rulebook is a real reason to look again, for "Rules updated: re-check?".
    if (
        content.state == ContentState.resolving.value
        and previous is not None
        and previous.content_version_id == latest.id
        and previous.rulebook_version == current_rulebook_version(session)
        # A changed fact is a real reason too, once an admin has asked.
        and rereview.pending(session, content_id, previous) is None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Add a new version to review it again."
        )
    if content.state == ContentState.ai_review.value and previous is not None:
        run = engine_client.review_status(previous.engine_review_id, session)
        if not can_start_again(content.state, run):
            message = (
                "This review is still running."
                if run == "running"
                else ("This review has already finished.")
            )
            raise HTTPException(status.HTTP_409_CONFLICT, message)
    limits.check_reviews_today(session)
    try:
        budget.check(session)
    except BudgetExceeded as exc:
        raise limits.over(str(exc)) from None
    # A review against no rules would pass everything, so say what is missing instead.
    try:
        rulebook_at(session)
    except RulebookNotFound:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This workspace has no approved rules yet. Ask an admin to upload the brand "
            "guidelines and approve the rules, then review again.",
        ) from None
    source = content_source(content, latest)
    rulebook_version = current_rulebook_version(session)
    review = Review(
        content_version_id=latest.id,
        engine_review_id=engine_client.start_review(
            latest.id, content.channel, rulebook_version, source, org_id=user.org_id
        ),
        channel=content.channel,
        rulebook_version=rulebook_version,
    )
    session.add(review)
    move_content(
        session,
        content,
        ContentState.ai_review,
        user,
        rulebook_version=rulebook_version,
    )
    session.commit()
    return review
