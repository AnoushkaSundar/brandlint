"""Hidden-content check (always critical): zero-width characters, text coloured
like its background, sub-4pt fonts, HTML comments, and image/OCR text absent
from the visible copy. Cites the built-in SEC-HIDDEN-CONTENT rule."""

from __future__ import annotations

from app.contracts import CheckType, Finding, Severity
from app.engine.checks.context import (
    _SEC_TEXT,
    SEC_HIDDEN_CONTENT,
    CheckContext,
    make_finding,
)
from app.engine.chunking import ParsedChunk

_ZERO_WIDTH = {"\u200b", "‌", "‍", "⁠", "﻿"}


def _same_colour(style: dict) -> bool:
    color, bg = style.get("color"), style.get("background")
    return bool(color and bg and color.lower() == bg.lower())


def _hidden_reasons(chunk: ParsedChunk) -> list[str]:
    style = chunk.style or {}
    reasons: list[str] = []
    if any(c in _ZERO_WIDTH for c in chunk.text):
        reasons.append("zero-width characters")
    if _same_colour(style):
        reasons.append("text the same colour as its background")
    font_pt = style.get("font_pt")
    if font_pt is not None and font_pt < 4:
        reasons.append(f"font size {font_pt}pt (under 4pt)")
    if style.get("hidden"):
        reasons.append("hidden via CSS/aria")
    if style.get("from_comment"):
        reasons.append("text inside an HTML comment")
    return reasons


def _is_visible(chunk: ParsedChunk) -> bool:
    style = chunk.style or {}
    return not (
        _hidden_reasons(chunk) or style.get("from_ocr")
    )


def check_hidden_content(
    chunks: list[ParsedChunk], ctx: CheckContext
) -> list[Finding]:
    findings: list[Finding] = []
    for chunk in chunks:
        reasons = _hidden_reasons(chunk)
        if reasons:
            findings.append(
                make_finding(
                    ctx,
                    check=CheckType.hidden_content,
                    severity=Severity.critical,
                    cited_text=_SEC_TEXT[SEC_HIDDEN_CONTENT],
                    explanation="Hidden content: " + "; ".join(reasons) + ".",
                    anchor=f"{chunk.id}:hidden",
                    spans=[{"chunk_id": chunk.id, "start": 0, "end": len(chunk.text)}],
                    rule_id=SEC_HIDDEN_CONTENT,
                    sources=[SEC_HIDDEN_CONTENT],
                )
            )

    # OCR text that doesn't appear in the visible copy.
    visible = " ".join(c.text for c in chunks if _is_visible(c)).lower()
    for chunk in chunks:
        style = chunk.style or {}
        text = chunk.text.strip()
        if style.get("from_ocr") and text and text.lower() not in visible:
            findings.append(
                make_finding(
                    ctx,
                    check=CheckType.hidden_content,
                    severity=Severity.critical,
                    cited_text=_SEC_TEXT[SEC_HIDDEN_CONTENT],
                    explanation=(
                        "Image text is not present in the visible copy "
                        "(possible hidden instruction or claim)."
                    ),
                    anchor=f"{chunk.id}:ocr",
                    spans=[{"chunk_id": chunk.id, "start": 0, "end": len(chunk.text)}],
                    rule_id=SEC_HIDDEN_CONTENT,
                    sources=[SEC_HIDDEN_CONTENT],
                )
            )
    return findings
