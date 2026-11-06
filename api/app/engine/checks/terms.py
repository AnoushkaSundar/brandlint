"""Banned / preferred terms and renamed product names.

Each term is governed by its own rule (``Term.rule_id``), so findings cite the
right rule and carry per-term severity. A match that exactly equals the term's
``preferred`` form is NOT flagged (so the correctly-cased brand name is safe even
when a mis-cased variant is banned). Overlapping matches on the same span are
de-duplicated.
"""

from __future__ import annotations

import re

from app.contracts import CheckType, Finding
from app.engine.checks.context import CheckContext, make_finding
from app.engine.chunking import ParsedChunk


def check_terms(chunks: list[ParsedChunk], ctx: CheckContext) -> list[Finding]:
    rules_by_id = {rule.id: rule for rule in ctx.rules}
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

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
            for chunk in chunks:
                for match in pattern.finditer(chunk.text):
                    # The correctly-cased preferred form is not a violation.
                    if match.group(0) == term.preferred:
                        continue
                    key = (chunk.id, match.start(), match.end())
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(
                        make_finding(
                            ctx,
                            check=CheckType.terminology,
                            severity=rule.severity,
                            cited_text=rule.text,
                            explanation=(
                                f"'{match.group(0)}' is not approved terminology; "
                                f"use '{term.preferred}'."
                            ),
                            anchor=f"{chunk.id}:{match.start()}:{match.end()}",
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
