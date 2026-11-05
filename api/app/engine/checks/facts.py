"""Fact expiry: content that states the value of a fact whose `valid_until` has
passed. Verified in code against the facts store; cites the fact."""

from __future__ import annotations

import re

from app.contracts import CheckType, Finding, Severity
from app.engine.checks.context import CheckContext, make_finding
from app.engine.chunking import ParsedChunk


def check_fact_expiry(chunks: list[ParsedChunk], ctx: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    for fact in ctx.facts:
        if fact.valid_until is None:
            continue
        expiry = fact.valid_until.date()
        if expiry >= ctx.as_of:
            continue  # still valid
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
                        f"{expiry.isoformat()}."
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
