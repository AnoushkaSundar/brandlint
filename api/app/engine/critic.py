"""The critic: plain code that gates every finding before a user can see it.

- "No source, no flag": a candidate that cites nothing, or cites a rule or fact
  missing from the pinned rulebook, becomes a `Gap`, never a `Finding`.
- Dedupes overlapping spans for the same source, keeping the strongest.
- Lowers confidence on AI findings where specialists disagree about a span.

It makes no model calls and every step is deterministic, so a given input always
produces the same output.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from app.contracts import (
    CheckType,
    Finding,
    FindingStatus,
    Gap,
    Severity,
    Trace,
    TraceStep,
    UnitType,
    Verdict,
)

# Multiplied into an AI finding's confidence when specialists conflict.
CONFLICT_FACTOR = 0.8

_VERDICT_RANK = {Verdict.VIOLATION: 1, Verdict.UNSURE: 0}
_SEVERITY_RANK = {
    Severity.low: 0,
    Severity.medium: 1,
    Severity.high: 2,
    Severity.critical: 3,
}


@dataclass
class Candidate:
    """A proposed finding. Unlike `Finding` it may be uncited: the critic decides."""

    review_id: str
    content_version_id: str
    check: CheckType
    tier: int
    verdict: Verdict
    severity: Severity
    confidence: float
    explanation: str
    unit_type: UnitType = UnitType.chunk
    spans: list[dict] = field(default_factory=list)
    rule_id: str | None = None
    rule_version: int | None = None
    fact_ids: list[str] = field(default_factory=list)
    cited_text: str = ""
    trace: Trace = field(default_factory=Trace)
    ai_generated: bool = True
    models_used: list[str] = field(default_factory=list)
    fix_available: bool = False
    # Set when the candidate came from an already-built tier-0 finding.
    finding_id: str | None = None
    # The inputs Replay needs. Never shown to a user.
    manifest: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.check = CheckType(self.check)
        self.verdict = Verdict(self.verdict)
        self.severity = Severity(self.severity)
        self.unit_type = UnitType(self.unit_type)

    @classmethod
    def from_finding(cls, finding: Finding) -> Candidate:
        return cls(
            review_id=finding.review_id,
            content_version_id=finding.content_version_id,
            check=finding.check,
            tier=finding.tier,
            verdict=finding.verdict,
            severity=finding.severity,
            confidence=finding.confidence,
            explanation=finding.explanation,
            unit_type=finding.unit_type,
            spans=[span.model_dump() for span in finding.spans],
            rule_id=finding.rule_id,
            rule_version=finding.rule_version,
            fact_ids=list(finding.fact_ids),
            cited_text=finding.cited_text,
            trace=finding.trace,
            ai_generated=finding.ai_generated,
            models_used=list(finding.models_used),
            fix_available=finding.fix_available,
            finding_id=finding.id,
        )

    def stable_id(self) -> str:
        if self.finding_id:
            return self.finding_id
        anchor = "|".join(
            [
                self.review_id,
                self.check.value,
                self.rule_id or "",
                ",".join(self.fact_ids),
                ",".join(
                    f"{s['chunk_id']}:{s['start']}:{s['end']}" for s in self.spans
                ),
            ]
        )
        digest = hashlib.sha256(anchor.encode()).hexdigest()[:12]
        return f"{self.review_id}:{self.check.value}:{digest}"


def _is_cited(
    candidate: Candidate,
    known_rule_ids: Collection[str],
    known_fact_ids: Collection[str],
) -> bool:
    has_source = bool(candidate.rule_id or candidate.fact_ids)
    if not has_source or not candidate.cited_text.strip():
        return False
    if candidate.rule_id and candidate.rule_id not in known_rule_ids:
        return False
    return all(fact_id in known_fact_ids for fact_id in candidate.fact_ids)


def _gap_id(candidate: Candidate) -> str:
    """Tied to the content, not the review, so re-reviewing the same draft repeats
    the id. Governance counts gaps, and one draft must not look like several."""
    anchor = "|".join(
        [
            candidate.content_version_id,
            candidate.check.value,
            candidate.rule_id or "",
            ",".join(candidate.fact_ids),
            ",".join(f"{s['chunk_id']}:{s['start']}:{s['end']}" for s in candidate.spans),
        ]
    )
    return f"gap:{hashlib.sha256(anchor.encode()).hexdigest()[:32]}"


def _to_gap(candidate: Candidate) -> Gap:
    return Gap(
        id=_gap_id(candidate),
        review_id=candidate.review_id,
        check=candidate.check,
        text=candidate.cited_text or candidate.explanation,
        explanation=candidate.explanation,
        created_at=datetime.now(UTC),
    )


def _overlaps(a: Candidate, b: Candidate) -> bool:
    return any(
        x["chunk_id"] == y["chunk_id"]
        and x["start"] < y["end"]
        and y["start"] < x["end"]
        for x in a.spans
        for y in b.spans
    )


def _strength(candidate: Candidate) -> tuple[int, int, int, float]:
    """Higher is stronger. A code verdict beats any AI one, because it has already
    streamed: dropping it here would leave a finding on screen but not in the record."""
    return (
        _VERDICT_RANK[candidate.verdict],
        1 if candidate.tier == 0 else 0,
        _SEVERITY_RANK[candidate.severity],
        candidate.confidence,
    )


def _dedupe(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Keep the strongest of any overlapping candidates citing the same source."""
    ordered = sorted(
        candidates,
        key=lambda c: (*(-x for x in _strength(c)), c.stable_id()),
    )
    kept: list[Candidate] = []
    seen_ids: set[str] = set()
    for candidate in ordered:
        candidate_id = candidate.stable_id()
        if candidate_id in seen_ids:
            continue
        same_source = (
            (kept_one.rule_id, kept_one.fact_ids)
            == (candidate.rule_id, candidate.fact_ids)
            and _overlaps(kept_one, candidate)
            for kept_one in kept
        )
        if any(same_source):
            continue
        seen_ids.add(candidate_id)
        kept.append(candidate)
    return kept


def _lower_conflicts(candidates: list[Candidate]) -> list[Candidate]:
    """Specialists conflict when they overlap but reach different verdicts.

    Only AI confidence moves: a tier-0 result is a fact about the text.
    """
    conflicted: set[str] = set()
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            if a.check != b.check and a.verdict != b.verdict and _overlaps(a, b):
                conflicted.update(c.stable_id() for c in (a, b) if c.tier != 0)

    lowered: list[Candidate] = []
    for candidate in candidates:
        if candidate.stable_id() not in conflicted:
            lowered.append(candidate)
            continue
        confidence = round(candidate.confidence * CONFLICT_FACTOR, 4)
        step = TraceStep(
            tool="critic",
            input_summary="overlapping findings from other specialists",
            output_summary=(
                f"specialists disagree; confidence {candidate.confidence} "
                f"lowered to {confidence}"
            ),
        )
        trace = candidate.trace.model_copy(
            update={"steps": [*candidate.trace.steps, step]}
        )
        lowered.append(replace(candidate, confidence=confidence, trace=trace))
    return lowered


def _to_finding(candidate: Candidate) -> Finding:
    return Finding(
        id=candidate.stable_id(),
        review_id=candidate.review_id,
        content_version_id=candidate.content_version_id,
        unit_type=candidate.unit_type,
        spans=candidate.spans,
        check=candidate.check,
        tier=candidate.tier,
        verdict=candidate.verdict,
        severity=candidate.severity,
        confidence=candidate.confidence,
        rule_id=candidate.rule_id,
        rule_version=candidate.rule_version,
        fact_ids=candidate.fact_ids,
        cited_text=candidate.cited_text,
        explanation=candidate.explanation,
        trace=candidate.trace,
        ai_generated=candidate.ai_generated,
        models_used=candidate.models_used,
        fix_available=candidate.fix_available,
        status=FindingStatus.open,
    )


def _already_blocked(candidate: Candidate, blocked_chunks: Collection[str]) -> bool:
    chunk_ids = {span["chunk_id"] for span in candidate.spans}
    return (
        candidate.verdict == Verdict.UNSURE
        and candidate.tier > 0
        and bool(chunk_ids)
        and chunk_ids <= set(blocked_chunks)
    )


def gate(
    candidates: Iterable[Candidate],
    *,
    known_rule_ids: Collection[str],
    known_fact_ids: Collection[str],
    blocked_chunks: Collection[str] = (),
) -> tuple[list[Finding], list[Gap]]:
    """Split candidates into findings a user may see and gaps for the gap log.

    `blocked_chunks` already carry a critical injection finding only a reviewer can
    clear, so an UNSURE about that same text would only make them clear it twice.
    """
    cited: list[Candidate] = []
    gaps: list[Gap] = []
    for candidate in candidates:
        if candidate.verdict == Verdict.PASS:
            continue
        if _is_cited(candidate, known_rule_ids, known_fact_ids):
            cited.append(candidate)
        else:
            gaps.append(_to_gap(candidate))

    cited = [c for c in cited if not _already_blocked(c, blocked_chunks)]
    survivors = _lower_conflicts(_dedupe(cited))
    survivors.sort(key=lambda c: (c.tier, c.stable_id()))
    return [_to_finding(c) for c in survivors], gaps
