"""Work that opens its own sessions still belongs to the org that asked for it.

A review runs in a background thread, and the fixer, Replay, the eval gate and the
governance agent make model calls through sessions they open themselves. Those sessions
are not the request's, so the org has to be handed to them, or the gateway has no org to
build its deny-list for and the call fails. These tests catch a route that forgets.
"""

from __future__ import annotations

import pytest
from app import db
from app.contracts import FixSuggestion
from app.tenancy import bound_org, org_sessions
from sqlalchemy.orm import Session


def test_org_sessions_binds_each_session_to_the_org(database):
    factory = org_sessions(db.get_sessionmaker(), "org-x")

    with factory() as first, factory() as second:
        assert bound_org(first) == bound_org(second) == "org-x"


def test_org_sessions_with_no_org_leaves_the_factory_alone(database):
    factory = db.get_sessionmaker()

    assert org_sessions(factory, None) is factory
    with factory() as session:
        assert bound_org(session) is None


@pytest.fixture
def captured(monkeypatch):
    """The session factories handed to the model-call builders."""
    seen: list = []

    def record(factory, model=None):
        seen.append(factory)

        def refuse(*args, **kwargs):
            raise RuntimeError("stop here: only the factory is being checked")

        return refuse

    monkeypatch.setattr("app.engine.graph.gateway_classify", record)
    monkeypatch.setattr("app.engine.graph.gateway_fix", record)
    return seen


def orgs_of(factories) -> set[str | None]:
    found = set()
    for factory in factories:
        with factory() as session:
            assert isinstance(session, Session)
            found.add(bound_org(session))
    return found


def test_replay_calls_the_model_for_the_callers_org(world, client_for, captured):
    client_for(world.a.admin).post(
        f"/engine/verdicts/{world.a.ids['finding_id']}/replay"
    )

    assert orgs_of(captured) == {world.a.org.id}


def test_the_eval_gate_calls_the_model_for_the_callers_org(world, client_for, captured):
    proposal = {
        "id": "p-test",
        "rule_id": world.a.ids["approved_rule_id"],
        "kind": "amendment",
        "current": "a",
        "suggested": "b",
        "evidence": {"count": 3, "examples": []},
        "status": "pending",
    }

    client_for(world.a.admin).post("/engine/eval/gate", json=proposal)

    assert orgs_of(captured) == {world.a.org.id}


def test_the_governance_agent_calls_the_model_for_the_callers_org(
    world, client_for, captured
):
    client_for(world.a.admin).post("/governance/run")

    assert orgs_of(captured) == {world.a.org.id}


def test_the_fixer_calls_the_model_for_the_callers_org(world, monkeypatch, captured):
    from app.clients import engine as engine_client

    suggestion = FixSuggestion(
        finding_id="f", original="a", suggested="b", diff="d", attempt=1
    )
    monkeypatch.setenv("USE_MOCK_ENGINE", "false")
    monkeypatch.setattr(
        "app.engine.agents.fixer.request_fix", lambda *a, **k: suggestion
    )

    engine_client.request_fix("f", 1, org_id=world.b.org.id)

    assert orgs_of(captured) == {world.b.org.id}


def test_starting_a_review_hands_its_background_sessions_the_org(world, monkeypatch):
    from app.engine import reviews

    handed = []
    monkeypatch.setattr(reviews._pool, "submit", lambda fn, *args: handed.append(args))

    reviews.start_review(
        "cv",
        "blog",
        1,
        __import__("app.contracts", fromlist=["ContentSource"]).ContentSource(
            data_class="public", text="Hello"
        ),
        org_id=world.a.org.id,
    )

    # run, channel, version, source, classify, second, then the session factory.
    session_factory = handed[0][6]
    with session_factory() as session:
        assert bound_org(session) == world.a.org.id
