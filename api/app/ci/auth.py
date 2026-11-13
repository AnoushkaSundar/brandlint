"""Who is calling a CI route: a service token, or a signed-in person.

A service token (`bl_...`) is accepted only on `/ci/*`, through these functions. Every other
route reads the session cookie or a login token, and a service token is neither, so there it
is a 401. The org comes from the token's own row, never from the request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.defaults import utc_now
from app.auth.dependencies import SessionDep, current_user
from app.auth.models import Organization, User
from app.auth.orgs import inactive_reason
from app.ci.models import ServiceToken
from app.tenancy.rls import auth_lookup
from app.tenancy.scoped import bind_org

TOKEN_PREFIX = "bl_"
# last_used_at is touched at most this often, so a busy job isn't a write on every call.
TOUCH_EVERY = timedelta(minutes=1)


def enabled() -> bool:
    return os.getenv("CI_INTEGRATION_ENABLED", "").lower() == "true"


def require_enabled() -> None:
    """The integration ships behind a flag: until it is on, its routes don't exist."""
    if not enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


def hash_token(raw: str) -> str:
    # The token is 32 random bytes, so a slow hash adds nothing. SHA-256 is enough.
    return hashlib.sha256(raw.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """A fresh token and its hash. The token is shown once and never kept."""
    raw = TOKEN_PREFIX + base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    return raw, hash_token(raw)


@dataclass
class Principal:
    kind: str  # "token" or "user"
    org_id: str
    name: str
    token_id: str | None = None
    user: User | None = None


def _bearer(request: Request) -> str | None:
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    return credentials if scheme.lower() == "bearer" and credentials else None


def _aware(moment: datetime) -> datetime:
    # SQLite hands back naive datetimes. They are stored as UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=utc_now().tzinfo)


def _unauthenticated(message: str = "Not signed in") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, message)


def _from_token(raw: str, session: Session) -> Principal:
    if not raw.startswith(TOKEN_PREFIX):
        raise _unauthenticated()
    digest = hash_token(raw)
    with auth_lookup(session):
        # unscoped-ok: a token is looked up by its hash to find out which org it is for
        row = session.scalar(select(ServiceToken).where(ServiceToken.token_hash == digest))
    if row is None or not hmac.compare_digest(row.token_hash, digest):
        raise _unauthenticated()
    now = utc_now()
    if row.revoked_at is not None:
        raise _unauthenticated("This token was revoked.")
    if row.expires_at is not None and _aware(row.expires_at) <= now:
        raise _unauthenticated("This token has expired.")
    reason = inactive_reason(session.get(Organization, row.org_id))
    if reason is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, reason)
    # From here every query is for the token's org.
    bind_org(session, row.org_id)
    if row.last_used_at is None or now - _aware(row.last_used_at) >= TOUCH_EVERY:
        row.last_used_at = now
        session.commit()
    return Principal("token", str(row.org_id), row.name, token_id=row.id)


def service_token(request: Request, session: SessionDep) -> Principal:
    """A service token, and only that."""
    raw = _bearer(request)
    if raw is None:
        raise _unauthenticated()
    return _from_token(raw, session)


def ci_principal(request: Request, session: SessionDep) -> Principal:
    """A service token or a signed-in person: the web run page uses the same routes."""
    raw = _bearer(request)
    if raw is not None and raw.startswith(TOKEN_PREFIX):
        return _from_token(raw, session)
    user = current_user(request, session)
    return Principal("user", str(user.org_id), user.name, user=user)


CurrentCIToken = Annotated[Principal, Depends(service_token)]
CIPrincipal = Annotated[Principal, Depends(ci_principal)]
