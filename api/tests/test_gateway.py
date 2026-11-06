"""Gateway stub tests — routing + mandatory logging, with the proxy transport
monkeypatched so no live LiteLLM is needed."""

from __future__ import annotations

import pytest
from app.db import Base
from app.gateway import llm, masking
from app.gateway.models import GatewayLog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def empty_deny_list(monkeypatch):
    # These tests cover routing and logging. test_masking.py covers masking.
    monkeypatch.setattr(masking, "deny_list", lambda bind: masking.DenyList((), frozenset()))


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


def test_restricted_is_not_sent_out_and_logs_error(session):
    with pytest.raises(NotImplementedError):
        llm.call(
            purpose="classify",
            data_class="restricted",
            rule_ids=[],
            payload={"messages": [{"role": "user", "content": "secret"}]},
            session=session,
        )
    row = session.query(GatewayLog).one()
    assert row.route == "ollama"
    assert row.status == "error"
    assert row.provider is None


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
