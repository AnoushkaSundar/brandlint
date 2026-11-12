from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.models import Organization, User
from app.auth.orgs import inactive_reason
from app.auth.security import SESSION_COOKIE, decode_token
from app.contracts import Role
from app.db import get_session

SessionDep = Annotated[Session, Depends(get_session)]


def _unauthenticated() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")


def _token_from(request: Request) -> str | None:
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and credentials:
        return credentials
    return request.cookies.get(SESSION_COOKIE)


def current_user(request: Request, session: SessionDep) -> User:
    token = _token_from(request)
    if token is None:
        raise _unauthenticated()
    try:
        claims = decode_token(token)
    except jwt.InvalidTokenError:
        raise _unauthenticated() from None

    # The stored role and org win over the token, so a role change takes effect at
    # once and a token can't name a workspace it wasn't issued for.
    user = session.get(User, claims["sub"])
    if user is None:
        raise _unauthenticated()
    reason = inactive_reason(session.get(Organization, user.org_id))
    if reason is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, reason)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    """Use as `Depends(require_roles(Role.admin))` to guard a route."""
    allowed = frozenset(role.value for role in roles)

    def check(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user

    return check
