from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, SessionDep, require_roles
from app.auth.models import User
from app.content import rereview, storage
from app.content.access import (
    latest_review,
    readable_content,
)
from app.content.models import Content, ContentVersion
from app.content.reviewing import add_version as _add_version
from app.content.reviewing import (
    begin_review,
)
from app.content.reviewing import versions as _versions
from app.content.schemas import (
    Channel,
    ContentDetail,
    ContentOut,
    ReviewOut,
    VersionOut,
)
from app.contracts import ContentState, DataClass, Role
from app.tenancy import limits, scoped, scoped_get
from app.workflow.models import Review

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


def _owned(content_id: str, user: User, session: Session) -> Content:
    content = readable_content(content_id, user, session)
    if content.creator_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only its creator can do this")
    return content


NUL_REFUSED = "Text can't contain a null character. Remove it and try again."


def _refuse_nul(*values: str | None) -> None:
    """Postgres can't store a null character, so it's refused before anything is saved.

    It isn't stripped: a review has to see exactly what was sent.
    """
    if any(value and "\x00" in value for value in values):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, NUL_REFUSED)


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
    _refuse_nul(text, file.filename if file else None)
    if file is None:
        return text, None

    data = file.file.read(storage.MAX_UPLOAD_BYTES + 1)
    try:
        upload = storage.check_upload(file.filename or "", data)
    except storage.UploadTooLarge as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(error)) from None
    except storage.UploadRejected as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    _refuse_nul(upload.text)
    return upload.text, upload


def _detail(session: Session, content: Content) -> ContentDetail:
    versions = _versions(session, content.id)
    review = latest_review(session, content.id)
    return ContentDetail(
        **ContentOut.model_validate(content).model_dump(),
        versions=[VersionOut.model_validate(v) for v in versions],
        latest_review=ReviewOut.model_validate(review) if review else None,
        rereview=rereview.pending(session, content.id, review),
    )


@router.get("", response_model=list[ContentOut])
def list_content(
    user: CurrentUser,
    session: SessionDep,
    source: Annotated[str | None, Query()] = None,
) -> list[Content]:
    query = scoped(session, Content).order_by(Content.created_at.desc())
    if source == "ci":
        # Copy that CI sent is for reviewers and admins. A creator never sees it.
        if user.role == Role.creator.value:
            return []
        query = query.where(Content.source == "ci")
    else:
        query = query.where(Content.source != "ci")
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
    _refuse_nul(title, source)
    limits.check_content(session)
    body, upload = _body_from(text, file)
    if upload is not None:
        limits.check_upload_size(session, len(upload.data))
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


@router.post(
    "/{content_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def start_review(content_id: str, user: Creator, session: SessionDep) -> Review:
    content = _owned(content_id, user, session)
    return begin_review(session, content, user)


@router.get("/versions/{version_id}/file")
def download_file(
    version_id: str, user: CurrentUser, session: SessionDep
) -> FileResponse:
    version = scoped_get(session, ContentVersion, version_id)
    if version is None or version.file_ref is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    readable_content(version.content_id, user, session)
    # The version was found inside the org, and its file must be in the org's folder too.
    if not storage.in_org_folder(version.file_ref, user.org_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")

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
