"""The fixer: a suggestion reaches a person only if it's safe."""

from __future__ import annotations

import pytest
from app.contracts import Fact, Rule, Term
from app.db import Base
from app.engine import models
from app.engine.agents import fixer, language
from app.engine.brand import BrandData
from app.engine.chunking import sha256_text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

TONE = Rule(
    id="R-TONE-02", version=1, type="judgment", text="Stay calm.", clause_ref="§2.2",
    severity="medium", channel_scope=[], status="approved",
)
TERM_RULE = Rule(
    id="R-TERM-01", version=1, type="deterministic", text="Avoid superlatives.",
    clause_ref="§3.1", severity="medium", channel_scope=[], status="approved",
)
STATS = Rule(
    id="R-CLAIM-01", version=1, type="judgment", text="Every statistic must match.",
    clause_ref="§4.1", severity="high", channel_scope=[], status="approved",
)
TERM = Term(
    id="T", preferred="trusted", banned=["best-in-class"], rule_id=TERM_RULE.id,
)
FACT = Fact(
    id="F-002", statement="Customers cut onboarding time by 38% on average.",
    value="38%", source_doc="d", owner="o", data_class="public", version=1,
)
BRAND = BrandData(rules=[TONE, TERM_RULE, STATS], facts=[FACT], terms=[TERM])
TEXT = "Tarnhollow Landing is the best-in-class way to start. Visit us."


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    fixer._attempts.clear()
    fixer._rejected.clear()
    monkeypatch.setattr(fixer, "load_brand", lambda session, version: BRAND)


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(
        engine, tables=[models.Chunk.__table__, models.Finding.__table__]
    )
    with sessionmaker(bind=engine, expire_on_commit=False, class_=Session)() as s:
        yield s


def seed(session, *, text=TEXT, quote="best-in-class", rule=TERM_RULE, facts=(), **over):
    session.add(
        models.Chunk(
            id="cv:0", content_version_id="cv", ordinal=0, kind="paragraph", text=text,
            content_hash=sha256_text(text), data_class="public", style=None,
        )
    )
    start = text.index(quote)
    base = {
        "id": "f1", "review_id": "rev", "content_version_id": "cv", "unit_type": "chunk",
        "spans": [{"chunk_id": "cv:0", "start": start, "end": start + len(quote)}],
        "check": "terminology", "tier": 0, "verdict": "VIOLATION", "severity": "medium",
        "confidence": 1.0, "rule_id": rule.id if rule else None, "rule_version": 1,
        "fact_ids": list(facts), "cited_text": rule.text if rule else FACT.statement,
        "explanation": "Not approved.", "trace": {}, "ai_generated": False,
        "models_used": [], "fix_available": True, "status": "open",
        "manifest": {
            "channel": "blog", "fmt": "text", "rulebook_version": 1, "as_of": "2026-11-07",
        },
    }
    session.add(models.Finding(**(base | over)))
    session.commit()


def rewrite(text):
    return lambda *args: {"rewrite": text}


def never(*args):
    raise AssertionError("must not call the specialist")


def ask(session, fix_call, classify=never, attempt=1):
    return fixer.request_fix("f1", attempt, session, fix_call=fix_call, classify=classify)


def test_a_clean_fix_is_returned_with_a_diff(session):
    seed(session)
    fix = ask(session, rewrite("trusted"))
    assert (fix.original, fix.suggested, fix.attempt) == ("best-in-class", "trusted", 1)
    assert fix.diff == "- best-in-class\n+ trusted"


@pytest.mark.parametrize(
    "bad",
    [
        "trusted, see https://evil.example/now",
        "trusted by 500 teams",
        "trusted by Acme",
        "",
        "best-in-class",
        "world class " + "and so on " * 12,
    ],
)
def test_a_rewrite_that_adds_anything_is_refused(session, bad):
    seed(session)
    with pytest.raises(fixer.NoSafeFix):
        ask(session, rewrite(bad))


def test_a_rewrite_that_keeps_the_banned_term_is_refused(session):
    seed(session)
    with pytest.raises(fixer.NoSafeFix):
        ask(session, rewrite("the best-in-class"))


def test_a_banned_term_the_fix_introduces_is_refused(session):
    other = Term(id="N", preferred="new hire", banned=["newbie"], rule_id=TERM_RULE.id)
    fixer_brand = BrandData(rules=BRAND.rules, facts=[], terms=[TERM, other])
    seed(session)
    fixer.load_brand = lambda session, version: fixer_brand
    with pytest.raises(fixer.NoSafeFix):
        ask(session, rewrite("newbie"))


def language_manifest():
    return {
        "kind": "language", "channel": "blog", "fmt": "text", "rulebook_version": 1,
        "as_of": "2026-11-07", "rule": TONE.model_dump(mode="json"), "model": "m",
    }


def model_says(verdict):
    def classify(data_class, rule_ids, payload, review_id):
        prompt = payload["messages"][-1]["content"]
        text = prompt.split("\n")[-2]
        return {
            "control_answer": language._WORD.findall(text)[0],
            "verdicts": [{
                "rule_id": rule_ids[0], "verdict": verdict, "span": None,
                "confidence": 0.9, "explanation": "x",
            }],
        }

    return classify


def test_the_language_specialist_must_clear_the_fix(session):
    seed(session, quote="Visit us", rule=TONE, manifest=language_manifest(), check="tone")
    assert ask(session, rewrite("Come see us"), model_says("PASS")).suggested
    fixer._attempts.clear()
    with pytest.raises(fixer.NoSafeFix):
        ask(session, rewrite("Come see us"), model_says("VIOLATION"))


def claim_manifest():
    return {
        "kind": "claim", "channel": "blog", "fmt": "text", "rulebook_version": 1,
        "as_of": "2026-11-07", "model": "m",
    }


def test_a_claim_fix_may_use_the_approved_figure(session):
    seed(
        session, text="Teams do it by 80% on average.", quote="by 80%", rule=STATS,
        facts=["F-002"], manifest=claim_manifest(), check="claim",
    )
    assert ask(session, rewrite("by 38%")).suggested == "by 38%"


def test_a_claim_fix_may_not_use_another_figure(session):
    seed(
        session, text="Teams do it by 80% on average.", quote="by 80%", rule=STATS,
        facts=["F-002"], manifest=claim_manifest(), check="claim",
    )
    with pytest.raises(fixer.NoSafeFix):
        ask(session, rewrite("by 80%, or so"))


def test_two_failures_end_in_unsure_and_no_third_call(session):
    seed(session)
    calls = []

    def bad(*args):
        calls.append(1)
        return {"rewrite": "trusted by 500 teams"}

    for attempt in (1, 2, 2):
        with pytest.raises(fixer.NoSafeFix):
            ask(session, bad, attempt=attempt)
    assert len(calls) == 2
    finding = session.get(models.Finding, "f1")
    assert finding.verdict == "UNSURE"
    assert finding.fix_available is False
    assert fixer.NO_SAFE_FIX in finding.explanation


def test_the_second_attempt_is_told_what_was_rejected(session):
    seed(session)
    seen = []

    def spy(data_class, rule_ids, payload, review_id):
        seen.append(payload["messages"][1]["content"])
        return {"rewrite": "trusted by 500 teams"}

    for attempt in (1, 2):
        with pytest.raises(fixer.NoSafeFix):
            ask(session, spy, attempt=attempt)
    assert "rejected" not in seen[0]
    assert "trusted by 500 teams" in seen[1]


@pytest.mark.parametrize("raw", [[], 7, None, {"nope": 1}, {"content": "sorry"}])
def test_a_malformed_reply_is_no_fix(session, raw):
    seed(session)
    with pytest.raises(fixer.NoSafeFix):
        ask(session, lambda *args: raw)


def test_a_model_error_is_no_fix(session):
    seed(session)

    def down(*args):
        raise TimeoutError

    with pytest.raises(fixer.NoSafeFix):
        ask(session, down)


def test_a_finding_without_a_fix_makes_no_call(session):
    seed(session, fix_available=False)
    with pytest.raises(fixer.NoSafeFix):
        ask(session, never)


def test_a_document_level_finding_makes_no_call(session):
    seed(session, spans=[])
    with pytest.raises(fixer.NoSafeFix):
        ask(session, never)


def test_an_unknown_finding_makes_no_call(session):
    with pytest.raises(fixer.NoSafeFix):
        ask(session, never)


def test_content_stays_in_a_delimited_block(session):
    seed(session)
    seen = []

    def spy(data_class, rule_ids, payload, review_id):
        seen.append(payload)
        return {"rewrite": "trusted"}

    ask(session, spy)
    assert "<<<MATERIAL-" in seen[0]["messages"][1]["content"]
    assert seen[0]["messages"][0]["role"] == "system"
