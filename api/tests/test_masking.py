"""Masking: nothing protected reaches the proxy, and it fails closed."""

from __future__ import annotations

import threading

import pytest
from app.admin import models as admin_models
from app.admin.seed import seed_brand
from app.contracts import Rule
from app.db import Base
from app.engine.agents import language
from app.engine.checks import CheckContext
from app.engine.chunking import ParsedChunk, sha256_text
from app.gateway import llm, masking
from app.gateway.models import GatewayLog, TokenVault
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

DENY = masking.DenyList(
    terms=("Bluewren", "Redstart"), allowed=frozenset({"tarnhollow landing"})
)


@pytest.fixture()
def engine():
    built = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        built, tables=[GatewayLog.__table__, TokenVault.__table__]
    )
    return built


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def fixed_deny_list(monkeypatch):
    monkeypatch.setattr(masking, "deny_list", lambda bind: DENY)


@pytest.fixture()
def sent(monkeypatch):
    bodies: list[dict] = []

    def transport(body):
        bodies.append(body)
        return {
            "model": "m",
            "choices": [{"message": {"content": body["messages"][-1]["content"]}}],
        }

    monkeypatch.setattr(llm, "_chat_completion", transport)
    return bodies


def no_presidio(monkeypatch):
    def fail(text):
        raise AssertionError("Presidio must not run for this data class")

    monkeypatch.setattr(masking, "analyze", fail)


def call(session, text, data_class="public", review_id="rev"):
    return llm.call(
        "classify", data_class, ["R1"],
        {"messages": [{"role": "user", "content": text}]},
        session=session, review_id=review_id,
    )


def test_a_codename_never_reaches_the_proxy_even_on_public_content(
    session, sent, monkeypatch
):
    no_presidio(monkeypatch)
    out = call(session, "Meet Bluewren today")
    assert sent[0]["messages"][-1]["content"] == "Meet [PRODUCT_1] today"
    assert out == {"content": "Meet Bluewren today"}
    row = session.query(GatewayLog).one()
    assert row.masked == {"PRODUCT": 1}


def test_case_variants_are_masked_and_restored_exactly(session, sent, monkeypatch):
    no_presidio(monkeypatch)
    out = call(session, "BLUEWREN and bluewren")
    assert "luewren" not in sent[0]["messages"][-1]["content"].lower()
    assert out == {"content": "BLUEWREN and bluewren"}


def test_a_word_containing_a_codename_is_left_alone(session, sent, monkeypatch):
    no_presidio(monkeypatch)
    call(session, "Bluewrens fly")
    assert sent[0]["messages"][-1]["content"] == "Bluewrens fly"


def test_system_messages_are_masked_too(session, sent, monkeypatch):
    no_presidio(monkeypatch)
    llm.call(
        "classify", "public", [],
        {"messages": [
            {"role": "system", "content": "About Bluewren"},
            {"role": "user", "content": "Hi"},
        ]},
        session=session,
    )
    assert sent[0]["messages"][0]["content"] == "About [PRODUCT_1]"


def test_a_value_keeps_its_token_across_calls_in_a_review(session, sent, monkeypatch):
    no_presidio(monkeypatch)
    call(session, "Redstart then Bluewren")
    call(session, "Bluewren")
    assert sent[0]["messages"][-1]["content"] == "[PRODUCT_1] then [PRODUCT_2]"
    assert sent[1]["messages"][-1]["content"] == "[PRODUCT_2]"


def test_tokens_are_scoped_to_a_review(session, sent, monkeypatch):
    no_presidio(monkeypatch)
    call(session, "Redstart", review_id="a")
    call(session, "Bluewren", review_id="b")
    assert sent[1]["messages"][-1]["content"] == "[PRODUCT_1]"


def test_parallel_calls_share_one_token(engine, monkeypatch):
    results = []
    barrier = threading.Barrier(6)

    def worker():
        barrier.wait(5)
        results.append(masking._token_for("Bluewren", "PRODUCT", "rev", engine))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert set(results) == {"[PRODUCT_1]"}
    with Session(engine) as session:
        assert session.query(TokenVault).count() == 1


@pytest.mark.parametrize("data_class", ["internal", "confidential"])
def test_personal_data_is_masked(session, sent, monkeypatch, data_class):
    monkeypatch.setattr(
        masking, "analyze",
        lambda text: [{"entity_type": "PERSON", "start": 4, "end": 7, "score": 0.9}],
    )
    out = call(session, "Ask Sam now", data_class)
    assert sent[0]["messages"][-1]["content"] == "Ask [PERSON_1] now"
    assert out == {"content": "Ask Sam now"}


def test_brand_terms_presidio_calls_people_stay_readable(session, sent, monkeypatch):
    text = "Tarnhollow Landing helps"
    monkeypatch.setattr(
        masking, "analyze",
        lambda t: [{"entity_type": "PERSON", "start": 0, "end": 18, "score": 0.85}],
    )
    call(session, text, "internal")
    assert sent[0]["messages"][-1]["content"] == text


def test_presidio_outage_stops_the_call(session, sent, monkeypatch):
    def down(text):
        raise OSError("presidio down")

    monkeypatch.setattr(masking, "analyze", down)
    with pytest.raises(OSError, match="presidio"):
        call(session, "Ask Sam", "confidential")
    assert sent == []
    assert session.query(GatewayLog).one().status == "error"


def test_deny_list_failure_stops_the_call(session, sent, monkeypatch):
    def broken(bind):
        raise OSError("no brand data")

    monkeypatch.setattr(masking, "deny_list", broken)
    with pytest.raises(OSError, match="brand"):
        call(session, "Anything")
    assert sent == []


def test_a_typed_token_cannot_reveal_a_codename(session, sent, monkeypatch):
    no_presidio(monkeypatch)
    call(session, "Bluewren")  # Now [PRODUCT_1] means Bluewren in this review.
    out = call(session, "What is [PRODUCT_1]?")
    assert out == {"content": "What is [PRODUCT_1]?"}
    assert "[PRODUCT_1]" not in sent[1]["messages"][-1]["content"]


def test_a_reply_cant_use_a_token_from_another_call(session, monkeypatch):
    no_presidio(monkeypatch)
    replies = iter(["ok", "It is [PRODUCT_1]"])

    def transport(body):
        return {"model": "m", "choices": [{"message": {"content": next(replies)}}]}

    monkeypatch.setattr(llm, "_chat_completion", transport)
    call(session, "Bluewren")
    assert call(session, "Hello") == {"content": "It is [PRODUCT_1]"}


def test_unmask_reaches_nested_output():
    tokens = {"[PRODUCT_1]": "Bluewren"}
    value = {"a": ["[PRODUCT_1]", {"b": "see [PRODUCT_1]"}], "n": 1}
    assert masking.unmask(value, tokens) == {
        "a": ["Bluewren", {"b": "see Bluewren"}], "n": 1,
    }


def test_confidential_images_are_refused(session, sent):
    with pytest.raises(ValueError, match="visuals"):
        llm.call(
            "visual", "confidential", [],
            {"messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:x"}},
            ]}]},
            session=session,
        )
    assert sent == []


def test_public_image_parts_pass_through_and_text_parts_are_masked(
    session, sent, monkeypatch
):
    no_presidio(monkeypatch)
    image = {"type": "image_url", "image_url": {"url": "data:x"}}
    llm.call(
        "visual", "public", [],
        {"messages": [{"role": "user", "content": [
            {"type": "text", "text": "Bluewren"}, image,
        ]}]},
        session=session,
    )
    assert sent[0]["messages"][0]["content"] == [
        {"type": "text", "text": "[PRODUCT_1]"}, image,
    ]


def test_language_agent_stays_valid_through_masking(session, monkeypatch):
    """The control answer and quote come back as tokens and must still check out."""
    no_presidio(monkeypatch)
    text = "Bluewren will fix everything for you"
    chunk = ParsedChunk(
        id="c", content_version_id="cv", ordinal=0, kind="paragraph", text=text,
        content_hash=sha256_text(text), data_class="confidential", style=None,
    )
    rule = Rule(
        id="R-TONE-02", version=1, type="judgment", text="Stay calm.",
        clause_ref="§2", severity="medium", channel_scope=[], status="approved",
    )
    ctx = CheckContext(
        review_id="rev", content_version_id="cv", channel="blog", rules=[rule]
    )
    monkeypatch.setattr(
        masking, "analyze", lambda text: [],
    )

    def transport(body):
        prompt = body["messages"][-1]["content"]
        assert "Bluewren" not in prompt
        material = masking.re.search(r"<<<(MATERIAL-\w+)\n(.*)\n\1>>>", prompt, 16)
        words = material.group(2).split()
        first = "What is the first word" in prompt
        import json

        return {
            "model": "m",
            "choices": [{"message": {"content": json.dumps({
                "control_answer": words[0] if first else words[-1],
                "verdicts": [{
                    "rule_id": rule.id, "verdict": "VIOLATION",
                    "span": material.group(2), "confidence": 0.9,
                    "explanation": "[PRODUCT_1] overpromises.",
                }],
            })}}],
        }

    monkeypatch.setattr(llm, "_chat_completion", transport)

    def classify(data_class, rule_ids, payload, review_id):
        return llm.call(
            "classify", data_class, rule_ids, payload,
            session=session, review_id=review_id,
        )

    found = language.judge(chunk, rule, ctx, classify, flagged=(), model="m")
    assert found.verdict == "VIOLATION"
    assert found.spans[0] == {"chunk_id": "c", "start": 0, "end": len(text)}
    assert found.explanation == "Bluewren overpromises."


def test_the_deny_list_comes_from_protected_facts(engine, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(masking, "_deny_cache", None)
    Base.metadata.create_all(
        engine,
        tables=[
            admin_models.Rule.__table__,
            admin_models.Fact.__table__,
            admin_models.Term.__table__,
            admin_models.Asset.__table__,
        ],
    )
    with Session(engine) as session:
        seed_brand(session)
    deny = masking.deny_list(engine)
    assert "Bluewren" in deny.terms
    assert "tarnhollow landing" in deny.allowed
