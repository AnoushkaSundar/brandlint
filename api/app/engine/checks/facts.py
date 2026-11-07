"""Fact-backed tier-0 checks:

- `check_fact_expiry`: content stating the value of a fact whose `valid_until`
  (now a date) has passed; cites the fact.
- `check_confidential_terms`: a protected fact's value (a codename) appearing in
  content — always critical. This is the deterministic backstop; the gateway's
  masking deny-list (block 4) is the other layer.

Findings are shown to anyone who can see the review, including outside agencies,
so a protected fact's statement must never appear in one. These findings cite a
rule instead, and an expired protected fact is cited without its statement.
"""

from __future__ import annotations

import re

from app.contracts import CheckType, DataClass, Finding, Rule, Severity
from app.engine.checks.context import (
    _SEC_TEXT,
    SEC_CONFIDENTIAL,
    CheckContext,
    brand_rule,
    make_finding,
)
from app.engine.chunking import ParsedChunk

_PROTECTED = {DataClass.confidential, DataClass.restricted}
_EXPIRED_PROTECTED_CITATION = "An approved fact that has expired (details restricted)."


def _confidentiality_rule(ctx: CheckContext) -> Rule | None:
    """The brand rule against naming codenames, or None for the built-in."""
    return brand_rule(ctx, "codename")


def check_fact_expiry(chunks: list[ParsedChunk], ctx: CheckContext) -> list[Finding]:
    rule = brand_rule(ctx, "valid-until")
    findings: list[Finding] = []
    for fact in ctx.facts:
        if fact.valid_until is None or fact.valid_until >= ctx.as_of:
            continue  # no expiry, or still valid
        value = (fact.value or "").strip()
        if not value:
            continue
        pattern = re.compile(re.escape(value), re.IGNORECASE)
        for chunk in chunks:
            match = pattern.search(chunk.text)
            if not match:
                continue
            findings.append(
                make_finding(
                    ctx,
                    check=CheckType.claim,
                    severity=Severity.high,
                    cited_text=(
                        _EXPIRED_PROTECTED_CITATION
                        if fact.data_class in _PROTECTED
                        else fact.statement
                    ),
                    explanation=(
                        f"States '{value}', from a fact that expired on "
                        f"{fact.valid_until.isoformat()}."
                    ),
                    anchor=f"{chunk.id}:{fact.id}",
                    spans=[
                        {
                            "chunk_id": chunk.id,
                            "start": match.start(),
                            "end": match.end(),
                        }
                    ],
                    fact_ids=[fact.id],
                    sources=[fact.id],
                    rule=rule,
                )
            )
    return findings


def check_confidential_terms(
    chunks: list[ParsedChunk], ctx: CheckContext
) -> list[Finding]:
    rule = _confidentiality_rule(ctx)
    findings: list[Finding] = []
    for fact in ctx.facts:
        if fact.data_class not in _PROTECTED:
            continue
        value = (fact.value or "").strip()
        if not value:
            continue
        pattern = re.compile(rf"\b{re.escape(value)}\b", re.IGNORECASE)
        for chunk in chunks:
            for match in pattern.finditer(chunk.text):
                findings.append(
                    make_finding(
                        ctx,
                        check=CheckType.messaging,
                        severity=Severity.critical,
                        cited_text=rule.text if rule else _SEC_TEXT[SEC_CONFIDENTIAL],
                        explanation=f"'{match.group(0)}' must not appear in content.",
                        anchor=f"{chunk.id}:{match.start()}:conf:{fact.id}",
                        spans=[
                            {
                                "chunk_id": chunk.id,
                                "start": match.start(),
                                "end": match.end(),
                            }
                        ],
                        rule=rule,
                        rule_id=None if rule else SEC_CONFIDENTIAL,
                        sources=None if rule else [SEC_CONFIDENTIAL],
                    )
                )
    return findings
