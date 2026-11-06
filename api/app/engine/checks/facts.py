"""Fact-backed tier-0 checks:

- `check_fact_expiry`: content stating the value of a fact whose `valid_until`
  (now a date) has passed; cites the fact.
- `check_confidential_terms`: a confidential fact's value (a codename) appearing
  in content — always critical; cites the fact. This is the deterministic
  backstop; the gateway's masking deny-list (block 4) is the other layer.
"""

from __future__ import annotations

import re

from app.contracts import CheckType, DataClass, Finding, Severity
from app.engine.checks.context import CheckContext, make_finding
from app.engine.chunking import ParsedChunk


def check_fact_expiry(chunks: list[ParsedChunk], ctx: CheckContext) -> list[Finding]:
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
                    cited_text=fact.statement,
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
                )
            )
    return findings


def check_confidential_terms(
    chunks: list[ParsedChunk], ctx: CheckContext
) -> list[Finding]:
    findings: list[Finding] = []
    for fact in ctx.facts:
        if fact.data_class != DataClass.confidential:
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
                        cited_text=fact.statement,
                        explanation=(
                            f"'{value}' is a confidential codename and must not "
                            f"appear in published content."
                        ),
                        anchor=f"{chunk.id}:{match.start()}:conf:{fact.id}",
                        spans=[
                            {
                                "chunk_id": chunk.id,
                                "start": match.start(),
                                "end": match.end(),
                            }
                        ],
                        fact_ids=[fact.id],
                        sources=[fact.id],
                    )
                )
    return findings
