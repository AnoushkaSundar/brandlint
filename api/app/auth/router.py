import os

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.auth.dependencies import CurrentUser, SessionDep
from app.auth.models import Organization, User
from app.auth.orgs import inactive_reason
from app.auth.schemas import LoginRequest, LoginResponse, UserOut
from app.auth.security import (
    SESSION_COOKIE,
    SESSION_LIFETIME,
    create_token,
    verify_password,
)
from app.tenancy.rls import auth_lookup

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_is_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "").lower() == "true"


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response, session: SessionDep) -> LoginResponse:
    email = body.email.strip().lower()
    # unscoped-ok: emails are unique across orgs, and the org is read from the user found
    with auth_lookup(session):
        user = session.scalar(select(User).where(User.email == email))
    stored_hash = user.password_hash if user else None
    if not verify_password(body.password, stored_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect"
        )

    # Only after the password is right, so a stranger can't learn which orgs are suspended.
    reason = inactive_reason(session.get(Organization, user.org_id))
    if reason is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, reason)

    token = create_token(user)
    # httpOnly keeps the token away from scripts. A cookie also reaches the findings
    # stream, because EventSource can't send an Authorization header.
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=_cookie_is_secure(),
        path="/",
    )
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
