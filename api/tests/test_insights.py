"""Governance signals from reviews: override rates, vote splits, gaps and creators."""

import app.admin.models  # noqa: F401
import pytest
from app.admin.models import Gap
from app.auth.models import User
from app.auth.router import router as auth_router
from app.auth.security import SESSION_COOKIE, create_token, hash_password
from app.content.router import router as content_router
from app.contracts import Role
from app.db import Base, get_session
from app.insights.router import router as insights_router
from app.workflow.router import router as workflow_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# The mock engine's agency blog findings.
LOW = "fnd-agency-blog-03"  # R-TERM-03
MEDIUM = "fnd-agency-blog-02"  # R-TERM-01


@pytest.fixture(autouse=True)
def environment(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET", "a-test-only-secret-that-is-long-enough-for-hs256")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.delenv("USE_MOCK_ENGINE", raising=False)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        yield db


@pytest.fixture
def client_for(session):
    api = FastAPI()
    for router in (auth_router, content_router, workflow_router, insights_router):
        api.include_router(router)
    api.dependency_overrides[get_session] = lambda: session
    made = {}

    def make(role=Role.creator, handle=None):
        handle = handle or role.value
        if handle not in made:
            user = User(
                email=f"{handle}@example.com",
                name=handle.title(),
                role=role.value,
                password_hash=hash_password("not-used"),
            )
            session.add(user)
            session.commit()
            client = TestClient(api)
            client.cookies.set(SESSION_COOKIE, create_token(user))
            made[handle] = client
        return made[handle]

    return make


def resolving(client, title="Agency blog"):
    form = {
        "title": title,
        "channel": "blog",
        "source": "agency",
        "data_class": "public",
        "text": "Hello there",
    }
    content_id = client.post("/content", data=form).json()["id"]
    client.post(f"/content/{content_id}/reviews")
    client.post(f"/workflow/content/{content_id}/transitions", json={"to": "resolving"})
    return content_id


def decide(client, content_id, finding_id, action, reason=None):
    return client.post(
        f"/workflow/content/{content_id}/findings/{finding_id}/decisions",
        json={"action": action, "reason": reason, "fix_text": None},
    )


def signals(client, **params):
    return client.get("/insights/signals", params=params).json()


def test_a_confirmed_override_counts_toward_its_rule(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer)
    content_id = resolving(creator)
    decide(creator, content_id, LOW, "override", "A direct quote")
    decide(reviewer, content_id, LOW, "confirm_override")

    found = signals(client_for(Role.manager))

    term = found["override_rate_by_rule"]["R-TERM-03"]
    assert term == {"findings": 1, "overridden": 1, "rate": 1.0, "may_be_unclear": True}
    assert found["override_rate_by_rule"]["R-TERM-01"]["overridden"] == 0
    assert found["reviewed"] == 1


def test_a_pending_override_does_not_count(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, LOW, "override", "A direct quote")

    found = signals(client_for(Role.manager))

    assert found["override_rate_by_rule"]["R-TERM-03"]["overridden"] == 0


def test_top_rules_and_vote_splits_come_from_findings(client_for):
    resolving(client_for())

    found = signals(client_for(Role.admin))

    assert {rule["rule_id"] for rule in found["top_rules"]} >= {
        "R-TERM-01",
        "R-CLAIM-01",
    }
    assert found["vote_split_by_rule"]["R-CLAIM-01"] == {
        "voted": 1,
        "split": 0,
        "rate": 0.0,
    }
    assert sum(day["findings"] for day in found["findings_by_day"]) == 7


def test_filters_narrow_the_pieces(client_for):
    resolving(client_for())

    assert signals(client_for(Role.manager), source="in-house")["pieces"] == 0
    assert signals(client_for(Role.manager), source="agency")["pieces"] == 1


def test_gaps_are_listed(client_for, session):
    session.add(
        Gap(review_id="r1", check="tone", text="Too breezy", explanation="No rule")
    )
    session.commit()

    assert signals(client_for(Role.admin))["gaps"][0]["text"] == "Too breezy"


def test_a_creator_whose_overrides_are_mostly_rejected_is_a_signal(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer)
    for title in ("One", "Two", "Three"):
        content_id = resolving(creator, title)
        decide(creator, content_id, LOW, "override", "I like it")
        decide(reviewer, content_id, LOW, "reject_override", "It's a rule")

    found = signals(client_for(Role.manager))

    assert found["creator_signals"] == [
        {"creator": "Creator", "overrides": 3, "rejected_rate": 1.0}
    ]


def test_one_override_is_not_a_creator_signal(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, LOW, "override", "I like it")
    decide(client_for(Role.reviewer), content_id, LOW, "reject_override", "No")

    assert signals(client_for(Role.manager))["creator_signals"] == []


@pytest.mark.parametrize("role", [Role.creator, Role.reviewer, Role.legal])
def test_only_managers_and_admins_see_insights(client_for, role):
    assert client_for(role).get("/insights/signals").status_code == 403
