"""People in the admin's own workspace: list, add, change role, remove.

Every query is inside the caller's org, so another org's person is a 404. An org can't be
left without an admin: removing or demoting the last one is refused.
"""

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.schemas import UserOut
from app.auth.security import hash_password
from app.auth.workspaces.router import EMAIL
from app.contracts import Role
from app.tenancy import limits, scoped, scoped_get
from app.tenancy.rls import auth_lookup


class UserIn(BaseModel):
    email: str = Field(max_length=255)
    name: str = Field(min_length=1, max_length=120)
    role: Role
    # "agency" or "in-house", for creators.
    tag: str | None = Field(default=None, max_length=32)
    # They sign in with this and can't be mailed one, so the admin hands it over.
    password: str = Field(min_length=8, max_length=128)


class RoleIn(BaseModel):
    role: Role


def list_users(session: Session) -> list[User]:
    return list(session.scalars(scoped(session, User).order_by(User.name, User.email)))


def _person(session: Session, user_id: str) -> User:
    user = scoped_get(session, User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    return user


def _other_admins(session: Session, user: User) -> int:
    return session.scalar(
        scoped(session, User, func.count()).where(
            User.role == Role.admin.value, User.id != user.id
        )
    )


def add_user(session: Session, body: UserIn) -> User:
    email = body.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter a valid email."
        )
    limits.check_users(session)
    with auth_lookup(session):
        # unscoped-ok: emails are unique across every org
        taken = session.scalar(select(User.id).where(User.email == email))
    if taken is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That email already has an account."
        )
    user = User(
        email=email,
        name=body.name.strip(),
        role=body.role.value,
        tag=body.tag,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That email already has an account."
        ) from None
    return user


def change_role(session: Session, user_id: str, role: Role) -> User:
    user = _person(session, user_id)
    if (
        user.role == Role.admin.value
        and role is not Role.admin
        and _other_admins(session, user) == 0
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A workspace needs at least one admin."
        )
    user.role = role.value
    session.commit()
    return user


def remove_user(session: Session, user_id: str) -> None:
    user = _person(session, user_id)
    if user.role == Role.admin.value and _other_admins(session, user) == 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A workspace needs at least one admin."
        )
    try:
        session.delete(user)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This person has work on record, so they can't be removed. Change their role instead.",
        ) from None


__all__ = [
    "RoleIn",
    "UserIn",
    "UserOut",
    "add_user",
    "change_role",
    "list_users",
    "remove_user",
]
