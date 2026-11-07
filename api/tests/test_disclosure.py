"""The disclosure panel and masking preview, including after a cached re-run."""

from __future__ import annotations

import pytest
from app.contracts import Chunk
from app.db import Base
from app.engine import models as engine_models
from app.engine import reviews
from app.gateway import disclosure, masking, policy
from app.gateway.models import GatewayLog, TokenVault
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

TEXT = "Bluewren lands in spring."
OTHER = "Nothing secret here."


def chunk(text, data_class="public", number=0):
    return Chunk(
        id=f"cv:{number}", content_version_id="cv", ordinal=number, kind="paragraph",
        text=text, content_hash=f"h{number}", data_class=data_class,
    )


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(
        masking, "deny_list", lambda bind: masking.DenyList(("Bluewren",), frozenset())
    )
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(
        engine,
        tables=[
            GatewayLog.__table__, TokenVault.__table__, engine_models.Finding.__table__,
        ],
    )
    with Session(engine) as s:
        yield s


def serve(monkeypatch, *chunks):
    monkeypatch.setattr(reviews, "list_chunks", lambda review_id, session: list(chunks))


def log(session, model="claude-haiku-4-5", status="ok", review_id="rev"):
    session.add(
        GatewayLog(
            id=f"{model}{status}{review_id}", purpose="classify", data_class="public",
            rule_ids=[], model=model, route="litellm", review_id=review_id, status=status,
        )
    )
    session.commit()


def test_the_preview_shows_the_token_and_only_changed_passages(monkeypatch, session):
    serve(monkeypatch, chunk(OTHER, number=1), chunk(TEXT))
    preview = disclosure.masking_preview("rev", session)
    assert preview == {
        "original": TEXT,
        "sent": "[PRODUCT_1] lands in spring.",
    }


def test_the_preview_of_a_clean_piece_shows_it_unchanged(monkeypatch, session):
    serve(monkeypatch, chunk(OTHER))
    assert disclosure.masking_preview("rev", session) == {"original": OTHER, "sent": OTHER}


def test_a_preview_makes_no_model_call(monkeypatch, session):
    from app.gateway import llm

    monkeypatch.setattr(llm, "_chat_completion", None)
    serve(monkeypatch, chunk(TEXT))
    disclosure.masking_preview("rev", session)


def test_restricted_text_is_not_masked_because_it_stays_local(monkeypatch, session):
    serve(monkeypatch, chunk(TEXT, "restricted"))
    preview = disclosure.masking_preview("rev", session)
    assert preview["sent"] == TEXT


def test_disclosure_lists_models_routes_and_masked_entities(monkeypatch, session):
    serve(monkeypatch, chunk(TEXT))
    log(session)
    log(session, policy.LOCAL_MODEL)
    assert disclosure.disclosure("rev", session) == {
        "models": sorted(["claude-haiku-4-5", policy.LOCAL_MODEL]),
        "masked": {"PRODUCT": 1},
        "routes": ["cloud", "local"],
    }


def test_a_failed_call_or_another_review_is_not_disclosed(monkeypatch, session):
    serve(monkeypatch)
    log(session, "failed", status="error")
    log(session, "other", review_id="rev2")
    assert disclosure.disclosure("rev", session)["models"] == []


def test_a_re_run_served_from_the_cache_still_discloses(monkeypatch, session):
    """No calls are logged for this review, but its verdicts came from a model."""
    serve(monkeypatch, chunk(TEXT))
    session.add(
        engine_models.Finding(
            id="f", review_id="rev", content_version_id="cv", unit_type="chunk",
            spans=[], check="tone", tier=1, verdict="VIOLATION", severity="medium",
            confidence=0.9, rule_id="R", rule_version=1, fact_ids=[], cited_text="c",
            explanation="e", trace={}, ai_generated=True,
            models_used=["claude-haiku-4-5"],
        )
    )
    session.commit()
    assert disclosure.disclosure("rev", session) == {
        "models": ["claude-haiku-4-5"],
        "masked": {"PRODUCT": 1},
        "routes": ["cloud"],
    }
