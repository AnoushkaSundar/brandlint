"""Instruction-pattern detector: text addressed to an AI reviewer (prompt
injection). Always critical; cites the built-in SEC-INJECTION rule. Runs over
every chunk, including ones recovered from comments, metadata and OCR."""

from __future__ import annotations

import re

from app.contracts import CheckType, Finding, Severity
from app.engine.checks.context import (
    _SEC_TEXT,
    SEC_INJECTION,
    CheckContext,
    brand_rule,
    make_finding,
)
from app.engine.chunking import ParsedChunk

_INSTRUCTION_PATTERNS = [
    r"ignore (the |all )?previous",
    r"disregard (the )?(above|previous)",
    r"you are (now )?(a|an|the)\b",
    r"mark (this )?(as )?compliant",
    r"\bdo not flag\b",
    r"approve this (content|piece|review)?",
    r"as an ai\b",
    r"system prompt",
    r"new instructions?:",
]
_PATTERNS = re.compile("|".join(_INSTRUCTION_PATTERNS), re.IGNORECASE)


def detect_instructions(
    chunks: list[ParsedChunk], ctx: CheckContext
) -> list[Finding]:
    rule = brand_rule(ctx, "hidden text")
    findings: list[Finding] = []
    for chunk in chunks:
        match = _PATTERNS.search(chunk.text)
        if not match:
            continue
        findings.append(
            make_finding(
                ctx,
                check=CheckType.hidden_content,
                severity=Severity.critical,
                cited_text=rule.text if rule else _SEC_TEXT[SEC_INJECTION],
                explanation=(
                    f'Text addressed to an AI reviewer: "{match.group(0)}".'
                ),
                anchor=f"{chunk.id}:inject",
                spans=[
                    {"chunk_id": chunk.id, "start": match.start(), "end": match.end()}
                ],
                rule=rule,
                rule_id=SEC_INJECTION,
                sources=[rule.id if rule else SEC_INJECTION],
            )
        )
    return findings
