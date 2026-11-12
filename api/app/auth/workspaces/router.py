"""Workspace signup: a visitor creates a sandbox org and becomes its first admin.

Closed unless MULTI_TENANT_SIGNUP=true. Rate limited per client address. The org and its
admin are created in one transaction, so a failed signup leaves nothing behind. A new
org starts empty, and expires after SANDBOX_DAYS (7) days.
"""

import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.auth.defaults import utc_now
from app.auth.dependencies import CurrentUser, SessionDep
from app.auth.models import Organization, User
from app.auth.orgs import OrgKind, OrgStatus
from app.auth.router import set_session_cookie
from app.auth.schemas import LoginResponse, UserOut
from app.auth.security import create_token, hash_password
from app.contracts import Role
from app.tenancy import bind_org, scoped
from app.tenancy.rls import auth_lookup

router = APIRouter(prefix="/orgs", tags=["workspaces"])

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_attempts: dict[str, list[float]] = {}
_lock = threading.Lock()


class SignupRequest(BaseModel):
    workspace_name: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)


def _signup_open() -> bool:
    return os.getenv("MULTI_TENANT_SIGNUP", "").lower() == "true"


def _client_address(request: Request) -> str:
    # Behind our own proxy the last address it appended is the real client. Without one,
    # a header would be the caller's own claim, so it is ignored.
    if os.getenv("TRUST_PROXY", "").lower() == "true":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(address: str) -> bool:
    limit = int(os.getenv("SIGNUPS_PER_HOUR", "5"))
    now = time.monotonic()
    with _lock:
        recent = [t for t in _attempts.get(address, []) if now - t < 3600]
        if len(recent) >= limit:
            _attempts[address] = recent
            return True
        _attempts[address] = [*recent, now]
        return False


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


@router.post("", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    body: SignupRequest, request: Request, response: Response, session: SessionDep
) -> LoginResponse:
    if not _signup_open():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace signup isn't open.")
    if _rate_limited(_client_address(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many workspaces were created from here. Try again later.",
        )
    email = body.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter a valid email."
        )
    taken_message = "That email already has an account."
    with auth_lookup(session):
        # unscoped-ok: emails are unique across every org
        taken = session.scalar(select(User.id).where(User.email == email))
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, taken_message)

    org = Organization(
        name=body.workspace_name.strip(),
        slug=_slug(body.workspace_name),
        kind=OrgKind.sandbox.value,
        status=OrgStatus.active.value,
        expires_at=utc_now() + timedelta(days=int(os.getenv("SANDBOX_DAYS", "7"))),
    )
    session.add(org)
    session.flush()
    # From here the new user is written into the new org.
    bind_org(session, org.id)
    user = User(
        email=email,
        name=body.name.strip(),
        role=Role.admin.value,
        password_hash=hash_password(body.password),
        org_id=org.id,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, taken_message) from None

    token = create_token(user)
    set_session_cookie(response, token)
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


class Checklist(BaseModel):
    """What an empty workspace still needs, for the onboarding checklist."""

    guidelines: bool
    approved_rules: bool
    teammates: bool
    first_draft: bool


class WorkspaceOut(BaseModel):
    id: str
    name: str
    kind: str
    expires_at: datetime | None
    checklist: Checklist


@router.get("/current", response_model=WorkspaceOut)
def current_workspace(user: CurrentUser, session: SessionDep) -> WorkspaceOut:
    """The caller's own workspace. The org comes from the signed-in user, never the request."""
    from app.admin.models import IngestJob, Rule
    from app.content.models import Content

    org = session.get(Organization, user.org_id)

    def any_row(model, *where) -> bool:
        return session.scalar(scoped(session, model, func.count()).where(*where)) > 0

    return WorkspaceOut(
        id=org.id,
        name=org.name,
        kind=org.kind,
        expires_at=org.expires_at,
        checklist=Checklist(
            guidelines=any_row(IngestJob) or any_row(Rule),
            approved_rules=any_row(Rule, Rule.status == "approved"),
            teammates=session.scalar(scoped(session, User, func.count())) > 1,
            first_draft=any_row(Content),
        ),
    )
