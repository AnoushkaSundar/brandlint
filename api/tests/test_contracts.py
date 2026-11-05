"""Contract invariants that both owners rely on. Pure in-memory, no DB."""

from __future__ import annotations

import pytest
from app.contracts import CheckType, Finding, Rule, Severity, Verdict
from pydantic import ValidationError

_FINDING_BASE = {
    "id": "f1",
    "review_id": "r1",
    "content_version_id": "cv1",
    "unit_type": "chunk",
    "spans": [{"chunk_id": "c1", "start": 0, "end": 5}],
    "check": "tone",
    "tier": 1,
    "verdict": "PASS",
    "severity": "low",
    "confidence": 0.9,
    "cited_text": "hello",
    "explanation": "fine",
    "trace": {"steps": [], "sources": []},
    "ai_generated": False,
    "models_used": [],
    "fix_available": False,
    "status": "open",
}


def test_enum_string_values():
    assert Verdict.VIOLATION.value == "VIOLATION"
    assert {s.value for s in Severity} == {"low", "medium", "high", "critical"}
    assert CheckType.hidden_content.value == "hidden_content"


def test_finding_rejected_without_a_cited_source():
    # No rule_id and no fact_ids -> "no source, no flag".
    with pytest.raises(ValidationError):
        Finding(**_FINDING_BASE)


def test_finding_accepts_rule_citation():
    f = Finding(**{**_FINDING_BASE, "rule_id": "R1", "rule_version": 3})
    assert f.rule_id == "R1"
    assert f.spans[0].chunk_id == "c1"


def test_finding_accepts_fact_citation():
    f = Finding(**{**_FINDING_BASE, "fact_ids": ["FACT1"]})
    assert f.fact_ids == ["FACT1"]


def test_confidence_must_be_within_0_1():
    with pytest.raises(ValidationError):
        Finding(**{**_FINDING_BASE, "rule_id": "R1", "confidence": 1.5})


def test_rule_roundtrips_through_json():
    r = Rule(
        id="R1",
        version=1,
        type="judgment",
        text="Use an active voice.",
        clause_ref="3.2",
        severity="medium",
        channel_scope=["web", "email"],
        status="approved",
    )
    assert Rule.model_validate_json(r.model_dump_json()) == r


def test_v2_rule_required_text_and_term_rule_link():
    from app.contracts import Term

    rule = Rule(
        id="R-REQ-1", version=1, type="must_include",
        text="Ads must carry the standard disclaimer.", clause_ref="§5.1",
        severity="high", channel_scope=["ad"], status="approved",
        required_text="Results vary by organisation.",
    )
    assert rule.required_text == "Results vary by organisation."

    term = Term(id="t1", preferred="new hire", banned=["newbie"],
                rule_id="R-TERM-3", rule_version=2)
    assert term.rule_id == "R-TERM-3" and term.rule_version == 2
    # Fields are optional (back-compatible default).
    assert Rule(id="R2", version=1, type="judgment", text="x", clause_ref="§1",
                severity="low", status="approved").required_text is None
    assert Term(id="t2", preferred="ok").rule_id is None


def test_v2_fact_valid_until_is_a_date():
    from datetime import date

    from app.contracts import Fact

    fact = Fact(id="F1", statement="s", value="v", source_doc="d", owner="o",
                valid_until="2026-01-01", data_class="public", version=1)
    assert fact.valid_until == date(2026, 1, 1)
    assert isinstance(fact.valid_until, date)


def test_v2_chunk_model():
    from app.contracts import Chunk

    chunk = Chunk(id="cv1:0", content_version_id="cv1", ordinal=0,
                  kind="paragraph", text="hello", content_hash="h",
                  data_class="internal")
    assert chunk.style is None
    assert chunk.data_class.value == "internal"

