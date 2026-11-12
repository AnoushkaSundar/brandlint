"""Organisations: every user belongs to one, and an inactive one can't sign in.

The org on a request comes only from the user's row in the database. The org claim in
the token is a convenience and is never trusted.
"""

from datetime import timedelta
from typing import Annotated

import jwt
import pytest
from app.admin import models as admin_models  # noqa: F401
from app.auth.defaults import utc_now
from app.auth.dependencies import current_user
from app.auth.models import Organization, User
from app.auth.orgs import (
    DEMO_ORG_ID,
    DEMO_SLUG,
    OrgKind,
    OrgStatus,
    ensure_demo_org,
)
from app.auth.router import router
from app.auth.security import (
    SESSION_COOKIE,
    create_token,
    decode_token,
    hash_password,
)
from app.auth.seed import SEED_USERS, seed_users
from app.content import models as content_models  # noqa: F401
from app.contracts import Role
from app.db import Base, get_session
from app.workflow import models as workflow_models  # noqa: F401
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

SECRET = "a-test-only-secret-that-is-long-enough-for-hs256"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)


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

    @app.get("/whoami")
    def whoami(user: Annotated[User, Depends(current_user)]):
        return {"id": user.id, "org_id": user.org_id}

    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def add_org(session: Session, slug="acme", **fields) -> Organization:
    values = {"name": slug.title(), "slug": slug, "kind": "sandbox", "status": "active"}
    org = Organization(**{**values, **fields})
    session.add(org)
    session.commit()
    return org


def add_user(session: Session, org: Organization, email="sam@example.com") -> User:
    user = User(
        email=email,
        name="Sam",
        role=Role.creator.value,
        tag=None,
        password_hash=hash_password(PASSWORD),
        org_id=org.id,
    )
    session.add(user)
    session.commit()
    return user


def login(client: TestClient, user: User):
    return client.post("/auth/login", json={"email": user.email, "password": PASSWORD})


def token_for(user: User, **claims) -> str:
    now = utc_now()
    body = {
        "sub": user.id,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode({**body, **claims}, SECRET, algorithm="HS256")


def test_the_demo_org_is_created_once(session):
    first = ensure_demo_org(session)
    second = ensure_demo_org(session)

    assert first.id == second.id == DEMO_ORG_ID
    assert (first.name, first.slug, first.kind, first.status) == (
        "Tarnhollow",
        DEMO_SLUG,
        OrgKind.demo.value,
        OrgStatus.active.value,
    )
    assert first.expires_at is None
    assert len(session.scalars(select(Organization)).all()) == 1


@pytest.mark.parametrize(
    ("field", "value"), [("kind", "enterprise"), ("status", "deleted")]
)
def test_kind_and_status_are_limited(session, field, value):
    with pytest.raises(IntegrityError):
        add_org(session, **{field: value})


def test_slugs_are_unique(session):
    add_org(session, "acme")

    with pytest.raises(IntegrityError):
        add_org(session, "acme", name="Another")


def test_a_user_must_belong_to_an_org(session):
    """Through the table, because the ORM tests fill in a default org (see conftest)."""
    with pytest.raises(IntegrityError):
        session.execute(
            insert(User.__table__).values(
                id="u1", email="x@y.z", name="X", password_hash="h", role="creator"
            )
        )


def test_the_token_carries_the_users_org(session, client):
    user = add_user(session, add_org(session))

    assert decode_token(create_token(user))["org"] == user.org_id


def test_login_works_for_an_active_org(session, client):
    user = add_user(session, add_org(session))

    assert login(client, user).status_code == 200


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"status": "suspended"}, "suspended"),
        ({"expires_at": utc_now() - timedelta(minutes=1)}, "expired"),
    ],
)
def test_an_inactive_org_cant_log_in(session, client, fields, reason):
    user = add_user(session, add_org(session, **fields))

    response = login(client, user)

    assert response.status_code == 403
    assert reason in response.json()["detail"]
    assert SESSION_COOKIE not in response.cookies


def test_a_wrong_password_is_not_told_the_org_is_suspended(session, client):
    user = add_user(session, add_org(session, status="suspended"))

    response = client.post(
        "/auth/login", json={"email": user.email, "password": "wrong"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Email or password is incorrect"


def test_suspending_an_org_blocks_a_signed_in_user_at_once(session, client):
    org = add_org(session)
    user = add_user(session, org)
    assert login(client, user).status_code == 200
    assert client.get("/whoami").status_code == 200

    org.status = "suspended"
    session.commit()

    assert client.get("/whoami").status_code == 403


def test_a_forged_org_claim_gets_the_users_real_org(session, client):
    mine = add_org(session, "mine")
    other = add_org(session, "other")
    user = add_user(session, mine)

    response = client.get(
        "/whoami", headers={"Authorization": f"Bearer {token_for(user, org=other.id)}"}
    )

    assert response.status_code == 200
    assert response.json()["org_id"] == mine.id


def test_a_token_from_before_orgs_existed_still_works(session, client):
    user = add_user(session, add_org(session))

    response = client.get(
        "/whoami", headers={"Authorization": f"Bearer {token_for(user)}"}
    )

    assert response.status_code == 200


def test_a_user_whose_org_is_missing_is_refused(session, client):
    user = add_user(session, add_org(session))
    session.delete(session.get(Organization, user.org_id))
    session.commit()

    response = client.get(
        "/whoami", headers={"Authorization": f"Bearer {token_for(user)}"}
    )

    assert response.status_code == 403


def test_seeding_puts_every_demo_user_in_the_demo_org(session):
    created = seed_users(session)

    assert created == len(SEED_USERS)
    orgs = {user.org_id for user in session.scalars(select(User))}
    assert orgs == {DEMO_ORG_ID}
    assert session.get(Organization, DEMO_ORG_ID).kind == "demo"


def test_seeding_twice_changes_nothing(session):
    seed_users(session)

    assert seed_users(session) == 0
    assert len(session.scalars(select(Organization)).all()) == 1
