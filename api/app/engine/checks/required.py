"""MUST_INCLUDE required elements per channel. Looks for the rule's
``required_text`` (the exact phrase that must appear), not the rule sentence; if
it's absent for a channel in scope, flag it (document-level) and cite the rule.
A must_include rule with no ``required_text`` is skipped (nothing concrete to
require), so a post carrying the real phrase is no longer falsely flagged.
"""

from __future__ import annotations

import re
import unicodedata

from app.contracts import CheckType, Finding, RuleType
from app.engine.checks.context import CheckContext, make_finding
from app.engine.chunking import ParsedChunk


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


def check_required_elements(
    chunks: list[ParsedChunk], ctx: CheckContext
) -> list[Finding]:
    haystack = _norm(" ".join(c.text for c in chunks))
    findings: list[Finding] = []
    for rule in ctx.rules:
        if rule.type != RuleType.must_include:
            continue
        if rule.channel_scope and ctx.channel not in rule.channel_scope:
            continue
        required = rule.required_text
        if not required:
            continue
        if _norm(required) not in haystack:
            findings.append(
                make_finding(
                    ctx,
                    check=CheckType.required_element,
                    severity=rule.severity,
                    cited_text=required,
                    explanation=(
                        f"Required element for '{ctx.channel}' is missing: "
                        f'"{required}".'
                    ),
                    anchor=rule.id,
                    unit_type="document",
                    rule=rule,
                )
            )
    return findings
