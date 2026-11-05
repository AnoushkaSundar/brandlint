"""Banned / preferred terms and renamed product names. Cites the terminology
rule that governs the term list."""

from __future__ import annotations

import re

from app.contracts import CheckType, Finding, Rule
from app.engine.checks.context import CheckContext, make_finding
from app.engine.chunking import ParsedChunk


def check_terms(
    chunks: list[ParsedChunk], ctx: CheckContext, *, rule: Rule
) -> list[Finding]:
    findings: list[Finding] = []
    for term in ctx.terms:
        bad_variants = [b for b in list(term.banned) if b]
        if term.renamed_from:
            bad_variants.append(term.renamed_from)
        for bad in bad_variants:
            pattern = re.compile(rf"\b{re.escape(bad)}\b", re.IGNORECASE)
            for chunk in chunks:
                for match in pattern.finditer(chunk.text):
                    findings.append(
                        make_finding(
                            ctx,
                            check=CheckType.terminology,
                            severity=rule.severity,
                            cited_text=rule.text,
                            explanation=(
                                f"'{bad}' is not approved terminology; "
                                f"use '{term.preferred}'."
                            ),
                            anchor=f"{chunk.id}:{match.start()}:{bad.lower()}",
                            spans=[
                                {
                                    "chunk_id": chunk.id,
                                    "start": match.start(),
                                    "end": match.end(),
                                }
                            ],
                            rule=rule,
                        )
                    )
    return findings
