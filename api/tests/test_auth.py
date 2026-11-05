"""Login, sessions and role checks. Permissions must hold on the server, so these
tests call the API directly, including with forged and expired tokens.
"""

from datetime import timedelta
from typing import Annotated

import jwt
import pytest
from app.admin import models as admin_models  # noqa: F401
from app.auth.database import Base, get_session, utc_now
from app.auth.dependencies import require_roles
from app.auth.models import User
from app.auth.roles import Role
from app.auth.router import router
from app.auth.security import (
    SESSION_COOKIE,
    create_token,
    hash_password,
    verify_password,
)
from app.auth.seed import DEFAULT_PASSWORD, SEED_USERS, seed_users
from app.content import models as content_models  # noqa: F401
from app.workflow import models as workflow_models  # noqa: F401
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

SECRET = "a-test-only-secret-that-is-long-enough-for-hs256"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        yield db


@pytest.fixture
def client(session):
    app = FastAPI()
    app.include_router(router)

    @app.get("/admin-only")
    def admin_only(user: Annotated[User, Depends(require_roles(Role.ADMIN))]):
        return {"id": user.id}

    @app.get("/reviewers-and-managers")
    def reviewers_and_managers(
        user: Annotated[User, Depends(require_roles(Role.REVIEWER, Role.MANAGER))],
    ):
        return {"id": user.id}

    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def add_user(session: Session, role: Role = Role.CREATOR, email="sam@example.com"):
    user = User(
        email=email,
        name="Sam",
        role=role,
        tag=None,
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    session.commit()
    return user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_the_user_and_a_token(client, session):
    user = add_user(session, Role.REVIEWER)

    response = client.post(
        "/auth/login", json={"email": user.email, "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == user.email
    assert body["user"]["role"] == "reviewer"
    assert "password_hash" not in body["user"]
    claims = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"])
    assert claims["sub"] == user.id
    assert claims["role"] == "reviewer"


def test_login_sets_a_cookie_scripts_cannot_read(client, session):
    user = add_user(session)

    response = client.post(
        "/auth/login", json={"email": user.email, "password": PASSWORD}
    )

    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "secure" not in cookie


def test_cookie_is_secure_when_configured(client, session, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    user = add_user(session)

    response = client.post(
        "/auth/login", json={"email": user.email, "password": PASSWORD}
    )

    assert "secure" in response.headers["set-cookie"].lower()


def test_email_is_matched_regardless_of_case_and_spaces(client, session):
    add_user(session, email="sam@example.com")

    response = client.post(
        "/auth/login", json={"email": "  SAM@Example.com ", "password": PASSWORD}
    )

    assert response.status_code == 200


def test_a_wrong_password_and_an_unknown_email_look_the_same(client, session):
    user = add_user(session)

    wrong_password = client.post(
        "/auth/login", json={"email": user.email, "password": "wrong"}
    )
    unknown_email = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert "set-cookie" not in wrong_password.headers


def test_unknown_email_cannot_pass_with_the_placeholder_hash_password(client):
    response = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "no-such-user"}
    )

    assert response.status_code == 401


def test_passwords_are_hashed():
    stored = hash_password(PASSWORD)

    assert PASSWORD not in stored
    assert verify_password(PASSWORD, stored)
    assert not verify_password("wrong", stored)
    assert not verify_password(PASSWORD, "not-a-valid-hash")
    assert not verify_password(PASSWORD, None)


def test_me_requires_a_session(client):
    assert client.get("/auth/me").status_code == 401


def test_me_works_with_the_cookie(client, session):
    user = add_user(session)
    client.post("/auth/login", json={"email": user.email, "password": PASSWORD})

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == user.id


def test_me_works_with_a_bearer_token(client, session):
    user = add_user(session)

    response = client.get("/auth/me", headers=bearer(create_token(user)))

    assert response.status_code == 200


def test_logout_ends_the_browser_session(client, session):
    user = add_user(session)
    client.post("/auth/login", json={"email": user.email, "password": PASSWORD})

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def claims_for(user: User, **overrides) -> dict:
    now = utc_now()
    return {
        "sub": user.id,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(hours=1),
    } | overrides


def test_an_expired_token_is_rejected(client, session):
    user = add_user(session)
    token = jwt.encode(
        claims_for(user, exp=utc_now() - timedelta(seconds=1)), SECRET, "HS256"
    )

    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_a_token_signed_with_another_secret_is_rejected(client, session):
    user = add_user(session)
    token = jwt.encode(claims_for(user), "another-secret-" * 4, "HS256")

    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_an_unsigned_token_is_rejected(client, session):
    user = add_user(session)
    token = jwt.encode(claims_for(user), key=None, algorithm="none")

    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_a_token_without_an_expiry_is_rejected(client, session):
    user = add_user(session)
    claims = claims_for(user)
    del claims["exp"]
    token = jwt.encode(claims, SECRET, "HS256")

    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_garbage_is_rejected(client):
    assert client.get("/auth/me", headers=bearer("garbage")).status_code == 401


def test_a_token_for_a_deleted_user_is_rejected(client, session):
    user = add_user(session)
    token = create_token(user)
    session.delete(user)
    session.commit()

    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_a_token_cannot_raise_its_own_role(client, session):
    creator = add_user(session, Role.CREATOR)
    token = jwt.encode(claims_for(creator, role="admin"), SECRET, "HS256")

    assert client.get("/admin-only", headers=bearer(token)).status_code == 403


def test_a_role_change_applies_to_tokens_already_issued(client, session):
    user = add_user(session, Role.ADMIN)
    token = create_token(user)
    assert client.get("/admin-only", headers=bearer(token)).status_code == 200

    user.role = Role.CREATOR
    session.commit()

    assert client.get("/admin-only", headers=bearer(token)).status_code == 403


@pytest.mark.parametrize("role", list(Role))
def test_each_role_gets_only_what_it_is_allowed(client, session, role):
    user = add_user(session, role)
    headers = bearer(create_token(user))

    admin_only = client.get("/admin-only", headers=headers).status_code
    mixed = client.get("/reviewers-and-managers", headers=headers).status_code

    assert admin_only == (200 if role is Role.ADMIN else 403)
    assert mixed == (200 if role in (Role.REVIEWER, Role.MANAGER) else 403)


def test_role_checks_require_a_session(client):
    assert client.get("/admin-only").status_code == 401


def test_a_missing_secret_stops_token_creation(session, monkeypatch):
    user = add_user(session)
    monkeypatch.delenv("JWT_SECRET")

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_token(user)


def test_seed_creates_every_role_and_both_creator_tags(session):
    assert seed_users(session) == len(SEED_USERS)

    users = list(session.scalars(select(User)))
    assert {user.role for user in users} == set(Role)
    tags = {user.tag for user in users if user.role == Role.CREATOR}
    assert tags == {None, "agency", "in-house"}
    assert len(users) == 7


def test_seed_is_safe_to_run_twice(session):
    seed_users(session)

    assert seed_users(session) == 0
    assert len(list(session.scalars(select(User)))) == len(SEED_USERS)


def test_seeded_users_can_sign_in(client, session):
    seed_users(session)

    for email, *_ in SEED_USERS:
        response = client.post(
            "/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 200
