"""Tier-0 router: the format x channel -> checks table, and `run_tier0` which
runs the applicable checks and returns all findings.

terms / fact_expiry / confidential / hidden_content / injection apply to every
text-bearing format; required_element applies where a channel can carry
must_include rules. Terms now resolve their governing rule via `Term.rule_id`,
so no rule needs to be passed in.
"""

from __future__ import annotations

from app.contracts import Finding
from app.engine.checks.context import CheckContext
from app.engine.checks.facts import check_confidential_terms, check_fact_expiry
from app.engine.checks.hidden import check_hidden_content
from app.engine.checks.injection import detect_instructions
from app.engine.checks.required import check_required_elements
from app.engine.checks.terms import check_terms
from app.engine.chunking import ParsedChunk

_TEXT_FORMATS = {"text", "docx", "pdf", "html"}


def checks_for(fmt: str, channel: str) -> tuple[str, ...]:
    """Which tier-0 checks run for a given format x channel."""
    checks = ["terms", "fact_expiry", "confidential", "hidden_content", "injection"]
    if fmt in _TEXT_FORMATS:
        checks.insert(3, "required_element")
    return tuple(checks)


def run_tier0(
    chunks: list[ParsedChunk], ctx: CheckContext, fmt: str
) -> list[Finding]:
    selected = checks_for(fmt, ctx.channel)
    findings: list[Finding] = []
    if "terms" in selected:
        findings += check_terms(chunks, ctx)
    if "fact_expiry" in selected:
        findings += check_fact_expiry(chunks, ctx)
    if "confidential" in selected:
        findings += check_confidential_terms(chunks, ctx)
    if "required_element" in selected:
        findings += check_required_elements(chunks, ctx)
    if "hidden_content" in selected:
        findings += check_hidden_content(chunks, ctx)
    if "injection" in selected:
        findings += detect_instructions(chunks, ctx)
    return findings
