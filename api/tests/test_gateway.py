"""Gateway stub tests — routing + mandatory logging, with the proxy transport
monkeypatched so no live LiteLLM is needed."""

from __future__ import annotations

import pytest
from app.contracts import DataClass
from app.db import Base
from app.gateway import llm, masking, policy
from app.gateway.models import GatewayLog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def empty_deny_list(monkeypatch):
    # These tests cover routing and logging. test_masking.py covers masking.
    monkeypatch.setattr(masking, "deny_list", lambda bind, org_id=None: masking.DenyList((), frozenset()))


@pytest.fixture()
def session() -> Session:
    # In-memory DB with just the gateway tables created from the shared Base.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[GatewayLog.__table__])
    with Session(engine) as s:
        yield s


def test_public_call_returns_parsed_output_and_logs(monkeypatch, session):
    captured = {}

    def fake_transport(body):
        captured["body"] = body
        # The model returns schema-shaped JSON as the message content.
        return {
            "model": "claude-haiku-5-5",
            "choices": [{"message": {"content": '{"verdict": "PASS", "rule_id": "R1"}'}}],
        }

    monkeypatch.setattr(llm, "_chat_completion", fake_transport)

    out = llm.call(
        purpose="classify",
        data_class="public",
        rule_ids=["R1", "R2"],
        payload={"messages": [{"role": "user", "content": "judge this"}]},
        session=session,
        review_id="rev1",
    )

    # Returns the parsed model output (contract/mock shape), not the raw envelope.
    assert out == {"verdict": "PASS", "rule_id": "R1"}
    assert "choices" not in out
    # deterministic + pinned
    assert captured["body"]["temperature"] == 0
    assert captured["body"]["model"] == "claude-haiku-4-5"

    row = session.query(GatewayLog).one()
    assert row.route == "litellm"
    assert row.status == "ok"
    assert row.purpose == "classify"
    assert row.rule_ids == ["R1", "R2"]
    assert row.review_id == "rev1"
    assert row.provider == "claude-haiku-5-5"


def restricted(session):
    return llm.call(
        purpose="classify",
        data_class="restricted",
        rule_ids=[],
        payload={"messages": [{"role": "user", "content": "secret"}]},
        session=session,
    )


def test_restricted_stays_on_the_local_model(monkeypatch, session):
    sent = {}

    def transport(body):
        sent.update(body)
        return {"model": "llama", "choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(llm, "_chat_completion", transport)
    restricted(session)
    assert sent["model"] == policy.LOCAL_MODEL
    row = session.query(GatewayLog).one()
    assert (row.route, row.status, row.model) == ("ollama", "ok", policy.LOCAL_MODEL)


def test_restricted_never_falls_back_to_the_cloud(monkeypatch, session):
    models = []

    def down(body):
        models.append(body["model"])
        raise TimeoutError

    monkeypatch.setattr(llm, "_chat_completion", down)
    with pytest.raises(TimeoutError):
        restricted(session)
    assert models == [policy.LOCAL_MODEL]
    assert session.query(GatewayLog).one().status == "error"


def test_a_call_the_table_forbids_is_blocked_and_logged(monkeypatch, session):
    monkeypatch.setattr(llm, "_chat_completion", None)
    monkeypatch.setitem(
        policy.TABLE,
        (DataClass.public, policy.CLOUD, "classify"),
        policy.Action.block,
    )
    with pytest.raises(llm.PolicyBlocked):
        llm.call(
            purpose="classify",
            data_class="public",
            rule_ids=[],
            payload={"messages": [{"role": "user", "content": "x"}]},
            session=session,
        )
    row = session.query(GatewayLog).one()
    assert (row.route, row.status) == ("blocked", "blocked")


def test_anything_without_a_row_is_blocked():
    assert policy.decide(DataClass.public, "classify", "unknown") == policy.Action.block
    assert policy.decide(DataClass.restricted, "classify") == policy.Action.block


def test_a_review_of_restricted_data_uses_a_different_cache_key():
    assert policy.model_for("restricted") != policy.model_for("public")


def mask_codename(monkeypatch, reply):
    monkeypatch.setattr(
        masking, "deny_list", lambda bind, org_id=None: masking.DenyList(("Bluewren",), frozenset())
    )
    monkeypatch.setattr(
        masking, "_token_for", lambda value, label, scope, bind, org_id: "[PRODUCT_1]"
    )
    monkeypatch.setattr(
        llm,
        "_chat_completion",
        lambda body: {"model": "m", "choices": [{"message": {"content": reply}}]},
    )


def public_call(session):
    return llm.call(
        purpose="classify",
        data_class="public",
        rule_ids=[],
        payload={"messages": [{"role": "user", "content": "Bluewren"}]},
        session=session,
    )


@pytest.mark.parametrize("reply", ["see [PRODUCT_9]", "It's Bluewren", "it's bluewren."])
def test_a_reply_holding_what_it_was_never_given_is_blocked(monkeypatch, session, reply):
    mask_codename(monkeypatch, reply)
    with pytest.raises(llm.LeakBlocked):
        public_call(session)
    row = session.query(GatewayLog).one()
    assert row.status == "blocked"
    assert "Bluewren" not in row.error


def test_the_tokens_a_reply_was_given_are_restored(monkeypatch, session):
    mask_codename(monkeypatch, '{"a": "[PRODUCT_1]"}')
    assert public_call(session) == {"a": "Bluewren"}


@pytest.mark.parametrize(
    "reply",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```json\n{"a": 1}\n```\n\nThere is nothing to check here.',
        'Here you go: {"a": 1} and that is all.',
    ],
)
def test_json_is_read_however_the_model_wraps_it(monkeypatch, session, reply):
    monkeypatch.setattr(
        llm,
        "_chat_completion",
        lambda body: {"model": "m", "choices": [{"message": {"content": reply}}]},
    )
    out = llm.call(
        purpose="classify",
        data_class="public",
        rule_ids=[],
        payload={"messages": [{"role": "user", "content": "x"}]},
        session=session,
    )
    assert out == {"a": 1}


@pytest.mark.parametrize("reply", ["sorry", "{broken", "a { b"])
def test_a_reply_without_json_stays_as_text(monkeypatch, session, reply):
    monkeypatch.setattr(
        llm,
        "_chat_completion",
        lambda body: {"model": "m", "choices": [{"message": {"content": reply}}]},
    )
    out = llm.call(
        purpose="classify",
        data_class="public",
        rule_ids=[],
        payload={"messages": [{"role": "user", "content": "x"}]},
        session=session,
    )
    assert out == {"content": reply}


def test_session_is_required():
    with pytest.raises((TypeError, ValueError)):
        llm.call(
            purpose="classify",
            data_class="public",
            rule_ids=[],
            payload={"messages": []},
            session=None,
        )


def test_transport_error_is_logged_and_raised(monkeypatch, session):
    def boom(body):
        raise RuntimeError("proxy down")

    monkeypatch.setattr(llm, "_chat_completion", boom)

    with pytest.raises(RuntimeError):
        llm.call(
            purpose="classify",
            data_class="public",
            rule_ids=["R1"],
            payload={"messages": [{"role": "user", "content": "x"}]},
            session=session,
        )
    row = session.query(GatewayLog).one()
    assert row.status == "error"
    assert "proxy down" in row.error
