"""Block 7: workspace signup, managing people in your own org, and the sandbox limits."""

from __future__ import annotations

import pytest
from app import db
from app.auth.models import Organization, User
from app.gateway import llm
from app.tenancy import bind_org, scoped
from fastapi.testclient import TestClient
from sqlalchemy import func, select

SIGNUP = {
    "workspace_name": "Acme Co",
    "name": "Ada",
    "email": "ada@acme.example",
    "password": "a-long-enough-password",
}


def count(model) -> int:
    with db.get_sessionmaker()() as session:
        return session.scalar(
            select(func.count()).select_from(model)
        )  # unscoped-ok: test


@pytest.fixture()
def anonymous(database, real_app, monkeypatch):
    monkeypatch.setenv("MULTI_TENANT_SIGNUP", "true")
    return TestClient(real_app, raise_server_exceptions=False)


def test_signup_creates_one_sandbox_org_with_one_admin(anonymous):
    response = anonymous.post("/orgs", json=SIGNUP)
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "admin"
    assert (count(Organization), count(User)) == (1, 1)
    with db.get_sessionmaker()() as session:
        org = session.scalars(select(Organization)).one()  # unscoped-ok: test
        assert org.kind == "sandbox" and org.expires_at is not None


def test_the_same_email_cannot_sign_up_twice(anonymous):
    assert anonymous.post("/orgs", json=SIGNUP).status_code == 201
    assert anonymous.post("/orgs", json=SIGNUP).status_code == 409
    assert (count(Organization), count(User)) == (1, 1)


def test_signup_is_closed_unless_switched_on(anonymous, monkeypatch):
    monkeypatch.delenv("MULTI_TENANT_SIGNUP")
    assert anonymous.post("/orgs", json=SIGNUP).status_code == 403
    assert count(Organization) == 0


def test_an_admin_sees_and_adds_people_only_in_their_own_org(world, client_for):
    admin = client_for(world.a.admin)
    listed = {u["id"] for u in admin.get("/admin/users").json()}
    assert listed == {p.id for p in world.a.people}

    made = admin.post(
        "/admin/users",
        json={
            "email": "new@a.example",
            "name": "New",
            "role": "creator",
            "password": "long-enough-pw",
        },
    )
    assert made.status_code == 201
    with db.get_sessionmaker()() as session:
        bind_org(session, world.a.org.id)
        assert (
            session.scalar(
                scoped(session, User, User.org_id).where(User.id == made.json()["id"])
            )
            == world.a.org.id
        )
    # Another org's person is a 404, and an admin can't be left out of their own org.
    assert (
        admin.patch(
            f"/admin/users/{world.b.creator.id}", json={"role": "admin"}
        ).status_code
        == 404
    )
    assert (
        admin.patch(
            f"/admin/users/{world.a.admin.id}", json={"role": "creator"}
        ).status_code
        == 409
    )
    assert admin.delete(f"/admin/users/{world.a.admin.id}").status_code == 409


def test_a_sandbox_org_stops_at_its_people_limit(world, client_for, monkeypatch):
    monkeypatch.setenv("SANDBOX_MAX_USERS", "3")  # the world's org already has three
    response = client_for(world.a.admin).post(
        "/admin/users",
        json={
            "email": "x@a.example",
            "name": "X",
            "role": "creator",
            "password": "long-enough-pw",
        },
    )
    assert response.status_code == 429


def test_a_sandbox_org_cannot_spend_past_its_model_budget(
    world, monkeypatch, model_calls
):
    monkeypatch.setenv("SANDBOX_MAX_LLM_CALLS_PER_DAY", "0")
    with db.get_sessionmaker()() as session:
        bind_org(session, world.a.org.id)
        with pytest.raises(llm.BudgetExceeded):
            llm.call(
                "classify",
                "public",
                [],
                {"messages": [{"role": "user", "content": "hi"}]},
                session=session,
            )
    assert model_calls == []
