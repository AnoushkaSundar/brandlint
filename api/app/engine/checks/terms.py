"""Banned / preferred terms and renamed product names.

Each term is governed by its own rule (``Term.rule_id``), so findings cite the
right rule and carry per-term severity. A match that exactly equals the term's
``preferred`` form is NOT flagged (so the correctly-cased brand name is safe even
when a mis-cased variant is banned). Overlapping matches are reduced to the
longest, so "Tarnhollow Onramp" is one finding, not one for "Onramp" as well.
"""

from __future__ import annotations

import re

from app.contracts import CheckType, Finding, Rule, Term
from app.engine.checks.context import CheckContext, make_finding
from app.engine.chunking import ParsedChunk


def check_terms(chunks: list[ParsedChunk], ctx: CheckContext) -> list[Finding]:
    rules_by_id = {rule.id: rule for rule in ctx.rules}
    matches: list[tuple[int, int, int, str, Term, Rule]] = []

    for term in ctx.terms:
        # No governing rule -> nothing to cite -> no flag ("no source, no flag").
        rule = rules_by_id.get(term.rule_id) if term.rule_id else None
        if rule is None:
            continue

        variants = [b for b in term.banned if b]
        if term.renamed_from:
            variants.append(term.renamed_from)

        for bad in variants:
            pattern = re.compile(rf"\b{re.escape(bad)}\b", re.IGNORECASE)
            for index, chunk in enumerate(chunks):
                for match in pattern.finditer(chunk.text):
                    # The correctly-cased preferred form is not a violation.
                    if match.group(0) == term.preferred:
                        continue
                    matches.append(
                        (index, match.start(), match.end(), match.group(0), term, rule)
                    )

    # Longest first, so a longer match wins over anything inside it.
    matches.sort(key=lambda m: (m[0], m[1] - m[2], m[1]))
    kept: list[tuple[int, int, int, str, Term, Rule]] = []
    for candidate in matches:
        index, start, end, *_ = candidate
        if not any(k[0] == index and start < k[2] and k[1] < end for k in kept):
            kept.append(candidate)

    findings: list[Finding] = []
    for index, start, end, text, term, rule in sorted(kept, key=lambda m: m[:3]):
        chunk = chunks[index]
        findings.append(
            make_finding(
                ctx,
                check=CheckType.terminology,
                severity=rule.severity,
                cited_text=rule.text,
                explanation=(
                    f"'{text}' is not approved terminology; use '{term.preferred}'."
                ),
                anchor=f"{chunk.id}:{start}:{end}",
                spans=[{"chunk_id": chunk.id, "start": start, "end": end}],
                rule=rule,
            )
        )
    return findings
