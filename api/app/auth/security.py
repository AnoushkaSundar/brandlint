import logging
import os
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.auth.defaults import utc_now
from app.auth.models import User

SESSION_COOKIE = "brandlint_session"
SESSION_LIFETIME = timedelta(hours=8)

_ALGORITHM = "HS256"
# The value in .env.example. The repo is public, so tokens signed with it can be forged.
_PLACEHOLDER_SECRET = "change-me"

logger = logging.getLogger(__name__)
_hasher = PasswordHasher()
# Verified when the email is unknown, so a miss takes as long as a wrong password.
_UNKNOWN_USER_HASH = _hasher.hash("no-such-user")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    try:
        matched = _hasher.verify(stored_hash or _UNKNOWN_USER_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return matched and stored_hash is not None


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set")
    if secret == _PLACEHOLDER_SECRET:
        logger.warning("JWT_SECRET is still the placeholder. Set a real value.")
    return secret


def create_token(user: User) -> str:
    now = utc_now()
    claims = {
        "sub": user.id,
        "role": user.role,
        "iat": now,
        "exp": now + SESSION_LIFETIME,
    }
    return jwt.encode(claims, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError if the token is forged, expired or malformed."""
    return jwt.decode(
        token,
        _secret(),
        algorithms=[_ALGORITHM],
        options={"require": ["exp", "sub", "role"]},
    )
