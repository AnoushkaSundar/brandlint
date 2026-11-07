"""Critic: no source no flag, dedupe, conflicts, and that it stays deterministic."""

from __future__ import annotations

from app.contracts import Trace, Verdict
from app.engine.critic import CONFLICT_FACTOR, Candidate, gate

RULES = {"R1", "R2"}
FACTS = {"F1"}


def cand(**over) -> Candidate:
    base = {
        "review_id": "rev", "content_version_id": "cv", "check": "tone", "tier": 1,
        "verdict": Verdict.VIOLATION, "severity": "medium", "confidence": 0.9,
        "explanation": "Why.", "spans": [{"chunk_id": "c1", "start": 0, "end": 10}],
        "rule_id": "R1", "rule_version": 1, "cited_text": "The rule.", "trace": Trace(),
    }
    return Candidate(**(base | over))


def run(*candidates):
    return gate(candidates, known_rule_ids=RULES, known_fact_ids=FACTS)


def test_cited_candidate_becomes_an_open_finding():
    findings, gaps = run(cand())
    assert (len(findings), gaps) == (1, [])
    assert findings[0].status == "open"


def test_uncited_goes_to_the_gap_log():
    findings, gaps = run(cand(rule_id=None, rule_version=None))
    assert findings == []
    assert gaps[0].review_id == "rev"
    assert gaps[0].explanation == "Why."


def test_unknown_rule_or_fact_or_empty_citation_is_a_gap():
    findings, gaps = run(
        cand(rule_id="R-INVENTED"),
        cand(rule_id=None, fact_ids=["F-INVENTED"]),
        cand(cited_text="  "),
    )
    assert (findings, len(gaps)) == ([], 3)


def test_fact_citation_is_enough():
    findings, _ = run(cand(rule_id=None, rule_version=None, fact_ids=["F1"]))
    assert findings[0].fact_ids == ["F1"]


def test_pass_is_never_shown_or_logged():
    assert run(cand(verdict=Verdict.PASS)) == ([], [])


def test_overlaps_for_the_same_rule_keep_the_strongest():
    unsure = cand(verdict=Verdict.UNSURE, confidence=1.0)
    violation = cand(
        spans=[{"chunk_id": "c1", "start": 5, "end": 15}], confidence=0.5
    )
    findings, _ = run(unsure, violation)
    assert [f.verdict for f in findings] == [Verdict.VIOLATION]


def test_tier0_beats_an_equal_ai_finding():
    ai = cand(check="terminology", confidence=1.0)
    code = cand(check="terminology", tier=0, ai_generated=False, confidence=1.0)
    findings, _ = run(ai, code)
    assert [f.tier for f in findings] == [0]


def test_touching_spans_other_chunks_and_other_rules_are_kept():
    findings, _ = run(
        cand(),
        cand(spans=[{"chunk_id": "c1", "start": 10, "end": 20}]),
        cand(spans=[{"chunk_id": "c2", "start": 0, "end": 10}]),
        cand(rule_id="R2"),
    )
    assert len(findings) == 4


def test_identical_candidates_collapse():
    findings, _ = run(cand(), cand())
    assert len(findings) == 1


def test_conflict_lowers_ai_confidence_and_says_so():
    tone = cand(confidence=0.9)
    messaging = cand(
        check="messaging", rule_id="R2", verdict=Verdict.UNSURE, confidence=0.5
    )
    findings, _ = run(tone, messaging)
    by_check = {f.check.value: f for f in findings}
    assert by_check["tone"].confidence == round(0.9 * CONFLICT_FACTOR, 4)
    assert by_check["messaging"].confidence == round(0.5 * CONFLICT_FACTOR, 4)
    assert by_check["tone"].trace.steps[-1].tool == "critic"


def test_conflict_never_lowers_tier0_confidence():
    code = cand(tier=0, ai_generated=False, confidence=1.0)
    ai = cand(check="messaging", rule_id="R2", verdict=Verdict.UNSURE)
    findings, _ = run(code, ai)
    assert next(f for f in findings if f.tier == 0).confidence == 1.0


def test_same_verdict_or_same_check_is_not_a_conflict():
    findings, _ = run(cand(), cand(check="messaging", rule_id="R2"))
    assert {f.confidence for f in findings} == {0.9}


def test_order_is_deterministic_and_tier0_first():
    a = cand(rule_id="R2", spans=[{"chunk_id": "c9", "start": 0, "end": 1}])
    b = cand(tier=0, ai_generated=False)
    first, _ = run(a, b)
    second, _ = run(b, a)
    assert [f.id for f in first] == [f.id for f in second]
    assert first[0].tier == 0


def test_re_reviewing_a_draft_repeats_the_gap_id():
    first = cand(rule_id=None, rule_version=None, review_id="rev-1")
    second = cand(rule_id=None, rule_version=None, review_id="rev-2")
    other_draft = cand(rule_id=None, rule_version=None, content_version_id="cv2")
    _, gaps = run(first, second, other_draft)
    assert gaps[0].id == gaps[1].id
    assert gaps[0].id != gaps[2].id


def test_code_beats_a_more_severe_ai_finding_on_the_same_source():
    code = cand(tier=0, ai_generated=False, severity="low", confidence=1.0)
    ai = cand(severity="high", confidence=1.0)
    findings, _ = run(ai, code)
    assert [f.tier for f in findings] == [0]


def on_chunk(chunk_id, verdict=Verdict.UNSURE):
    return cand(verdict=verdict, spans=[{"chunk_id": chunk_id, "start": 0, "end": 5}])


def gated(*candidates):
    findings, _ = gate(
        candidates,
        known_rule_ids={"R1"},
        known_fact_ids=set(),
        blocked_chunks={"blocked"},
    )
    return findings


def test_an_unsure_on_text_already_blocked_is_not_a_second_card():
    assert gated(on_chunk("blocked")) == []


def test_a_violation_on_blocked_text_stays():
    assert len(gated(on_chunk("blocked", Verdict.VIOLATION))) == 1


def test_an_unsure_elsewhere_stays():
    assert len(gated(on_chunk("clean"))) == 1


def test_an_unsure_spanning_blocked_and_clean_text_stays():
    found = on_chunk("blocked")
    found.spans = [*found.spans, {"chunk_id": "clean", "start": 0, "end": 5}]
    assert len(gated(found)) == 1
