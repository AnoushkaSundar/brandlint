"""Verdict cache and Replay, with a fake model."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from app.contracts import ContentSource, Fact, Rule, Term
from app.db import Base
from app.engine import models, replay, reviews
from app.engine.agents import language
from app.engine.brand import BrandData
from app.engine.cache import VerdictCache, cache_key
from app.engine.checks import CheckContext
from app.engine.chunking import ParsedChunk, sha256_text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TONE = Rule(
    id="R-TONE-02", version=1, type="judgment", text="Stay calm.",
    clause_ref="§2.2", severity="medium", channel_scope=[], status="approved",
)
TERM_RULE = Rule(
    id="R-TERM-03", version=1, type="deterministic", text="Say new hire.",
    clause_ref="§3.3", severity="low", channel_scope=[], status="approved",
)
TERM = Term(id="T1", preferred="new hire", banned=["newbie"], rule_id=TERM_RULE.id)
BRAND = BrandData(rules=[TONE, TERM_RULE], facts=[], terms=[TERM])
TEXT = "The newbie must act now"
TIMEOUT_S = 10


@pytest.fixture()
def factory(tmp_path):
    # A file, not one shared connection: reviews write from several threads.
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(
        engine,
        tables=[
            models.Chunk.__table__,
            models.Finding.__table__,
            models.ReviewCache.__table__,
        ],
    )
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


class Model:
    """Answers VIOLATION by default, and counts its calls."""

    def __init__(self, verdict="VIOLATION"):
        self.verdict = verdict
        self.calls = 0

    def __call__(self, data_class, rule_ids, payload, review_id):
        self.calls += 1
        if "find factual claims" in payload["messages"][0]["content"]:
            return {"claims": []}
        prompt = payload["messages"][-1]["content"]
        text = prompt.split("\n")[-2]
        words = language._WORD.findall(text)
        first = "What is the first word" in prompt
        return {
            "control_answer": words[0] if first else words[-1],
            "verdicts": [
                {
                    "rule_id": rule_ids[0], "verdict": self.verdict, "span": text,
                    "confidence": 0.8, "explanation": "Too pushy.",
                }
            ],
        }


def chunk(text=TEXT):
    return ParsedChunk(
        id="cv:0", content_version_id="cv", ordinal=0, kind="paragraph", text=text,
        content_hash=sha256_text(text), data_class="public", style=None,
    )


def ctx(**over):
    base = {"review_id": "rev", "content_version_id": "cv", "channel": "blog"}
    return CheckContext(**(base | over))


def judge(model, cache, flagged=(), text=TEXT, rule=TONE, **over):
    return language.judge(
        chunk(text), rule, ctx(**over), model, flagged=flagged, model="m", cache=cache
    )


def review(factory, model, text=TEXT):
    review_id = reviews.start_review(
        "cv1", "blog", 1, ContentSource(data_class="public", text=text),
        classify=model, session_factory=factory, brand_loader=lambda v: BRAND,
        gap_sink=lambda gaps: None,
    )
    run = reviews.get_run(review_id)
    assert run.finished.wait(TIMEOUT_S)
    return run


def findings_of(run):
    return [payload for name, payload in run.events if name == "finding"]


def test_a_second_review_of_the_same_text_skips_the_model(factory):
    model = Model()
    first = review(factory, model)
    calls = model.calls
    second = review(factory, model)
    assert calls == 2  # One tone check and one claim extraction.
    assert model.calls == calls
    assert [f["verdict"] for f in findings_of(second)] == [
        f["verdict"] for f in findings_of(first)
    ]


def test_a_cached_pass_is_a_pass(factory):
    cache = VerdictCache(factory)
    model = Model("PASS")
    assert judge(model, cache) is None
    assert judge(model, cache) is None
    assert model.calls == 1


def test_a_cached_pass_on_flagged_text_is_still_unsure(factory):
    cache = VerdictCache(factory)
    model = Model("PASS")
    assert judge(model, cache) is None
    found = judge(model, cache, flagged={"cv:0"})
    assert found.verdict == "UNSURE"
    assert model.calls == 1


def test_changing_text_rule_version_or_channel_misses(factory):
    cache = VerdictCache(factory)
    model = Model()
    judge(model, cache)
    judge(model, cache, text="Different words entirely here")
    judge(model, cache, rule=TONE.model_copy(update={"version": 2}))
    judge(model, cache, channel="linkedin")
    assert model.calls == 4


def test_failures_are_never_cached(factory):
    cache = VerdictCache(factory)

    def down(*args):
        raise TimeoutError

    assert judge(down, cache).verdict == "UNSURE"
    model = Model()
    assert judge(model, cache).verdict == "VIOLATION"
    assert model.calls == 1


def test_a_wrong_control_answer_is_never_cached(factory):
    cache = VerdictCache(factory)
    good = Model()

    def wrong(*args):
        return good(*args) | {"control_answer": "banana"}

    assert judge(wrong, cache).verdict == "UNSURE"
    assert judge(good, cache).verdict == "VIOLATION"
    assert good.calls == 2


def test_a_hit_needs_its_facts_unchanged(factory):
    cache = VerdictCache(factory)
    key = cache_key("x")
    cache.put(
        key, unit_type="claim", verdict="PASS", payload={"a": 1}, manifest={},
        depends_on=[{"fact_id": "F1", "version": 2}],
    )
    assert cache.get(key, {"F1": 2}) == {"a": 1}
    assert cache.get(key, {"F1": 3}) is None
    assert cache.get(key, {}) is None


def test_a_hit_expires_with_its_earliest_fact(factory):
    moment = datetime(2026, 11, 6, tzinfo=UTC)
    now = [moment]
    cache = VerdictCache(factory, now=lambda: now[0])
    key = cache_key("x")
    cache.put(
        key, unit_type="claim", verdict="PASS", payload={"a": 1}, manifest={},
        valid_until=moment + timedelta(days=1),
    )
    assert cache.get(key, {}) == {"a": 1}
    now[0] = moment + timedelta(days=1)
    assert cache.get(key, {}) is None


def test_a_stale_row_is_replaced(factory):
    cache = VerdictCache(factory)
    key = cache_key("x")
    for value in (1, 2):
        cache.put(
            key, unit_type="chunk", verdict="PASS", payload={"a": value}, manifest={}
        )
    assert cache.get(key, {}) == {"a": 2}


def test_replay_really_calls_the_model_and_matches(factory):
    model = Model()
    run = review(factory, model)
    finding = next(f for f in findings_of(run) if f["tier"] == 1)
    before = model.calls
    with factory() as session:
        result = replay.replay(finding["id"], session, model)
    assert model.calls == before + 1
    assert result["identical"] is True
    assert result["verdict"] == "VIOLATION"
    assert result["manifest"]["rule"]["id"] == TONE.id
    assert result["manifest"]["as_of"] == date.today().isoformat()


def test_replay_reports_a_different_answer(factory):
    run = review(factory, Model())
    finding = next(f for f in findings_of(run) if f["tier"] == 1)
    with factory() as session:
        result = replay.replay(finding["id"], session, Model("PASS"))
    assert result["identical"] is False
    assert result["verdict"] == "PASS"


def test_replay_of_a_code_finding_reruns_the_checks(factory, monkeypatch):
    monkeypatch.setattr(replay, "load_brand", lambda session, version: BRAND)
    model = Model()
    run = review(factory, model)
    finding = next(f for f in findings_of(run) if f["tier"] == 0)
    calls = model.calls
    with factory() as session:
        result = replay.replay(finding["id"], session, model)
    assert result["identical"] is True
    assert model.calls == calls


def test_replay_notices_a_rule_that_no_longer_fires(factory, monkeypatch):
    run = review(factory, Model())
    finding = next(f for f in findings_of(run) if f["tier"] == 0)
    empty = BrandData(rules=[TONE, TERM_RULE], facts=[], terms=[])
    monkeypatch.setattr(replay, "load_brand", lambda session, version: empty)
    with factory() as session:
        result = replay.replay(finding["id"], session, Model())
    assert result["identical"] is False
    assert result["verdict"] == "PASS"


def test_replay_of_an_unknown_finding_is_none(factory):
    with factory() as session:
        assert replay.replay("nope", session, Model()) is None


def test_replay_refuses_a_finding_with_no_manifest(factory):
    run = review(factory, Model())
    finding_id = findings_of(run)[0]["id"]
    with factory() as session:
        session.get(models.Finding, finding_id).manifest = None
        session.commit()
        with pytest.raises(replay.NotReplayable):
            replay.replay(finding_id, session, Model())


def test_manifests_never_reach_the_stream(factory):
    run = review(factory, Model())
    assert all("manifest" not in f for f in findings_of(run))


def test_stored_findings_replay_without_the_manifest_field(factory):
    run = review(factory, Model())
    review_id = findings_of(run)[0]["review_id"]
    with factory() as session:
        events = reviews.stored_events(review_id, session)
    assert all("manifest" not in payload for name, payload in events)


def test_facts_appear_in_the_manifest(factory):
    fact = Fact(
        id="F1", statement="s", value="v", source_doc="d", owner="o",
        data_class="public", version=3,
    )
    brand = BrandData(rules=[TONE], facts=[fact], terms=[])
    review_id = reviews.start_review(
        "cv1", "blog", 1, ContentSource(data_class="public", text=TEXT),
        classify=Model(), session_factory=factory, brand_loader=lambda v: brand,
        gap_sink=lambda gaps: None,
    )
    run = reviews.get_run(review_id)
    assert run.finished.wait(TIMEOUT_S)
    with factory() as session:
        row = session.query(models.Finding).filter_by(review_id=review_id).first()
    assert row.manifest["facts"] == [{"id": "F1", "version": 3}]


def test_a_broken_cache_only_costs_a_model_call():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    broken = VerdictCache(sessionmaker(bind=engine, class_=Session))
    model = Model()
    assert judge(model, broken).verdict == "VIOLATION"
    assert model.calls == 1


def test_replay_compares_verdicts_and_reports_span_drift(factory):
    model = Model()
    run = review(factory, model)
    finding = next(f for f in findings_of(run) if f["tier"] == 1)

    def narrower(data_class, rule_ids, payload, review_id):
        reply = model(data_class, rule_ids, payload, review_id)
        reply["verdicts"][0]["span"] = "newbie"
        return reply

    with factory() as session:
        result = replay.replay(finding["id"], session, narrower)
    assert result["identical"] is True
    assert result["manifest"]["spans_identical"] is False


def test_any_cache_failure_only_costs_a_model_call(factory, monkeypatch):
    def broken():
        raise SystemError("commit returned NULL")

    model = Model()
    assert judge(model, VerdictCache(broken)).verdict == "VIOLATION"
    assert model.calls == 1


def test_a_stale_cache_row_is_a_miss():
    class Stale:
        def get(self, key, facts):
            return {"old": "shape"}

        def put(self, key, **kwargs):
            pass

    model = Model()
    assert judge(model, Stale()).verdict == "VIOLATION"
    assert model.calls == 1
