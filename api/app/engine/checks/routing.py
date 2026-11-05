"""Tier-0 router: the format x channel -> checks table, and `run_tier0` which
runs the applicable checks and returns all findings.

terms / fact_expiry / hidden_content / injection apply to every text-bearing
format; required_element applies where a channel can carry must_include rules.
The terminology check needs the governing terminology rule passed in (the
rule->term binding is a rulebook decision, resolved by the orchestration layer).
"""

from __future__ import annotations

from app.contracts import Finding, Rule
from app.engine.checks.context import CheckContext
from app.engine.checks.facts import check_fact_expiry
from app.engine.checks.hidden import check_hidden_content
from app.engine.checks.injection import detect_instructions
from app.engine.checks.required import check_required_elements
from app.engine.checks.terms import check_terms
from app.engine.chunking import ParsedChunk

_TEXT_FORMATS = {"text", "docx", "pdf", "html"}


def checks_for(fmt: str, channel: str) -> tuple[str, ...]:
    """Which tier-0 checks run for a given format x channel."""
    checks = ["terms", "fact_expiry", "hidden_content", "injection"]
    if fmt in _TEXT_FORMATS:
        checks.insert(2, "required_element")
    return tuple(checks)


def run_tier0(
    chunks: list[ParsedChunk],
    ctx: CheckContext,
    fmt: str,
    *,
    terminology_rule: Rule | None = None,
) -> list[Finding]:
    selected = checks_for(fmt, ctx.channel)
    findings: list[Finding] = []
    if "terms" in selected and terminology_rule is not None and ctx.terms:
        findings += check_terms(chunks, ctx, rule=terminology_rule)
    if "fact_expiry" in selected:
        findings += check_fact_expiry(chunks, ctx)
    if "required_element" in selected:
        findings += check_required_elements(chunks, ctx)
    if "hidden_content" in selected:
        findings += check_hidden_content(chunks, ctx)
    if "injection" in selected:
        findings += detect_instructions(chunks, ctx)
    return findings
