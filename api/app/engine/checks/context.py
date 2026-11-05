"""Shared context and helpers for tier-0 code checks.

Tier-0 checks are pure functions: they take the parsed chunks plus the brand
data they need (terms, facts, rules) and return `Finding`s with tier=0,
ai_generated=False. Every finding cites a source — a brand rule, an approved
fact, or a built-in platform security rule — so "no source, no flag" holds.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

from app.contracts import (
    CheckType,
    Fact,
    Finding,
    Rule,
    Severity,
    Term,
    Trace,
    TraceStep,
    Verdict,
)

# Built-in platform security rules (not brand rules). Hidden content and prompt
# injection cite these so the finding always has a source.
SEC_HIDDEN_CONTENT = "SEC-HIDDEN-CONTENT"
SEC_INJECTION = "SEC-INJECTION"
_SEC_TEXT = {
    SEC_HIDDEN_CONTENT: (
        "Content must not hide text from the reader (zero-width characters, "
        "text coloured like its background, sub-4pt fonts, comments, metadata, "
        "or image text absent from the visible copy)."
    ),
    SEC_INJECTION: (
        "Content must not contain instructions addressed to an AI reviewer."
    ),
}


@dataclass
class CheckContext:
    review_id: str
    content_version_id: str
    channel: str
    terms: list[Term] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    as_of: date = field(default_factory=date.today)


def _finding_id(ctx: CheckContext, check: str, anchor: str) -> str:
    digest = hashlib.sha256(
        f"{ctx.review_id}|{check}|{anchor}".encode()
    ).hexdigest()[:12]
    return f"{ctx.review_id}:{check}:{digest}"


def make_finding(
    ctx: CheckContext,
    *,
    check: CheckType,
    severity: Severity,
    cited_text: str,
    explanation: str,
    anchor: str,
    spans: list[dict] | None = None,
    unit_type: str = "chunk",
    rule: Rule | None = None,
    rule_id: str | None = None,
    rule_version: int | None = None,
    fact_ids: list[str] | None = None,
    sources: list[str] | None = None,
    tool: str = "tier0",
) -> Finding:
    """Build a tier-0 Finding. Pass a brand `rule`, or an explicit `rule_id`
    (e.g. a built-in security rule), or `fact_ids` — at least one is required."""
    if rule is not None:
        rule_id = rule.id
        rule_version = rule.version
    return Finding(
        id=_finding_id(ctx, check.value, anchor),
        review_id=ctx.review_id,
        content_version_id=ctx.content_version_id,
        unit_type=unit_type,
        spans=spans or [],
        check=check,
        tier=0,
        verdict=Verdict.VIOLATION,
        severity=severity,
        confidence=1.0,
        rule_id=rule_id,
        rule_version=rule_version,
        fact_ids=fact_ids or [],
        cited_text=cited_text,
        explanation=explanation,
        trace=Trace(
            steps=[
                TraceStep(
                    tool=tool,
                    input_summary=f"{ctx.channel} content, rulebook data",
                    output_summary=explanation,
                )
            ],
            sources=sources or ([rule.clause_ref] if rule else []),
            model=None,
        ),
        ai_generated=False,
        models_used=[],
        fix_available=False,
        status="open",
    )
