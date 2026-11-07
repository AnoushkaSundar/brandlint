from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.rulebook import current_rulebook_version
from app.auth.dependencies import CurrentUser, SessionDep, require_roles
from app.auth.models import User
from app.clients import engine as engine_client
from app.content import storage
from app.content.access import (
    can_start_again,
    latest_review,
    readable_content,
)
from app.content.models import Content, ContentVersion
from app.content.schemas import (
    Channel,
    ContentDetail,
    ContentOut,
    ReviewOut,
    VersionOut,
)
from app.contracts import ContentSource, ContentState, DataClass, Role
from app.workflow.models import Review
from app.workflow.transitions import move_content

router = APIRouter(prefix="/content", tags=["content"])

Creator = Annotated[User, Depends(require_roles(Role.creator))]
Title = Annotated[str, Form(min_length=1, max_length=255)]
Source = Annotated[str, Form(min_length=1, max_length=255)]
PastedText = Annotated[str, Form()]
Upload = Annotated[UploadFile | None, File()]

# Once a piece has been submitted, new text would skip the review it's in.
LOCKED_STATES = {
    ContentState.reviewer_check.value,
    ContentState.manager_approval.value,
    ContentState.legal_signoff.value,
    ContentState.published.value,
    ContentState.rejected.value,
}
REVIEWABLE_STATES = {
    ContentState.draft.value,
    ContentState.ai_review.value,
    ContentState.resolving.value,
}


def _owned(content_id: str, user: User, session: Session) -> Content:
    content = readable_content(content_id, user, session)
    if content.creator_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only its creator can do this")
    return content


def _body_from(
    text: str, file: UploadFile | None
) -> tuple[str, storage.CheckedUpload | None]:
    # A browser sends an unnamed empty file when the file field is left blank.
    if file is not None and not file.filename:
        file = None
    has_text = bool(text.strip())
    if has_text and file is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Paste text or upload a file, not both.",
        )
    if not has_text and file is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Paste some text or upload a file."
        )
    if file is None:
        return text, None

    data = file.file.read(storage.MAX_UPLOAD_BYTES + 1)
    try:
        upload = storage.check_upload(file.filename or "", data)
    except storage.UploadTooLarge as error:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, str(error)
        ) from None
    except storage.UploadRejected as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)
        ) from None
    return upload.text, upload


def _add_version(
    session: Session,
    content: Content,
    user: User,
    text: str,
    upload: storage.CheckedUpload | None,
    file_name: str | None,
) -> ContentVersion:
    latest = session.scalar(
        select(func.max(ContentVersion.version)).where(
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
        version.file_ref = storage.save_upload(version.id, upload)
        version.file_name = file_name
    return version


def _versions(session: Session, content_id: str) -> list[ContentVersion]:
    return list(
        session.scalars(
            select(ContentVersion)
            .where(ContentVersion.content_id == content_id)
            .order_by(ContentVersion.version.desc())
        )
    )


def _detail(session: Session, content: Content) -> ContentDetail:
    versions = _versions(session, content.id)
    review = latest_review(session, content.id)
    return ContentDetail(
        **ContentOut.model_validate(content).model_dump(),
        versions=[VersionOut.model_validate(v) for v in versions],
        latest_review=ReviewOut.model_validate(review) if review else None,
    )


@router.get("", response_model=list[ContentOut])
def list_content(user: CurrentUser, session: SessionDep) -> list[Content]:
    query = select(Content).order_by(Content.created_at.desc())
    if user.role == Role.creator.value:
        query = query.where(Content.creator_id == user.id)
    return list(session.scalars(query))


@router.post("", response_model=ContentDetail, status_code=status.HTTP_201_CREATED)
def create_content(
    user: Creator,
    session: SessionDep,
    title: Title,
    channel: Annotated[Channel, Form()],
    source: Source,
    data_class: Annotated[DataClass, Form()],
    text: PastedText = "",
    file: Upload = None,
) -> ContentDetail:
    body, upload = _body_from(text, file)
    content = Content(
        title=title.strip(),
        channel=channel,
        source=source.strip(),
        data_class=data_class.value,
        creator_id=user.id,
    )
    session.add(content)
    session.flush()
    _add_version(session, content, user, body, upload, file.filename if file else None)
    # Committed here because the session dependency only commits after the response
    # is sent, and the browser goes straight to the new page.
    session.commit()
    return _detail(session, content)


@router.get("/{content_id}", response_model=ContentDetail)
def get_content(
    content_id: str, user: CurrentUser, session: SessionDep
) -> ContentDetail:
    return _detail(session, readable_content(content_id, user, session))


@router.post(
    "/{content_id}/versions",
    response_model=ContentDetail,
    status_code=status.HTTP_201_CREATED,
)
def add_version(
    content_id: str,
    user: Creator,
    session: SessionDep,
    text: PastedText = "",
    file: Upload = None,
) -> ContentDetail:
    content = _owned(content_id, user, session)
    if content.state in LOCKED_STATES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This content is locked and can't be edited."
        )
    body, upload = _body_from(text, file)
    _add_version(session, content, user, body, upload, file.filename if file else None)
    session.commit()
    return _detail(session, content)


def _content_source(content: Content, version: ContentVersion) -> ContentSource:
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


@router.post(
    "/{content_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def start_review(content_id: str, user: Creator, session: SessionDep) -> Review:
    content = _owned(content_id, user, session)
    if content.state not in REVIEWABLE_STATES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This content can't be reviewed in its current state."
        )
    latest = _versions(session, content_id)[0]
    previous = latest_review(session, content_id)
    # Reviewing the same text against the same rules would only wipe the decisions.
    # A new rulebook is a real reason to look again, for "Rules updated: re-check?".
    if (
        content.state == ContentState.resolving.value
        and previous is not None
        and previous.content_version_id == latest.id
        and previous.rulebook_version == current_rulebook_version(session)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Add a new version to review it again."
        )
    if content.state == ContentState.ai_review.value and previous is not None:
        run = engine_client.review_status(previous.engine_review_id, session)
        if not can_start_again(content.state, run):
            message = "This review is still running." if run == "running" else (
                "This review has already finished."
            )
            raise HTTPException(status.HTTP_409_CONFLICT, message)
    source = _content_source(content, latest)
    rulebook_version = current_rulebook_version(session)
    review = Review(
        content_version_id=latest.id,
        engine_review_id=engine_client.start_review(
            latest.id, content.channel, rulebook_version, source
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


@router.get("/versions/{version_id}/file")
def download_file(
    version_id: str, user: CurrentUser, session: SessionDep
) -> FileResponse:
    version = session.get(ContentVersion, version_id)
    if version is None or version.file_ref is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    readable_content(version.content_id, user, session)

    path = storage.stored_path(version.file_ref)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(
        path,
        media_type=storage.media_type(version.file_ref),
        filename=version.file_name,
        content_disposition_type=(
            "inline" if storage.is_image(version.file_ref) else "attachment"
        ),
        headers={"X-Content-Type-Options": "nosniff"},
    )
