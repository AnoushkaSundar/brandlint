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
