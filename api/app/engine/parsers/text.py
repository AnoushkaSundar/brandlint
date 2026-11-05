"""Plain-text parser. Blank-line-separated paragraphs; a short line followed by a
blank line and with no terminal punctuation is treated as a heading (a light
heuristic — structured formats carry real heading info).
"""

from __future__ import annotations

from app.engine.parsers.base import Block, BlockKind, NormalisedDoc


def _looks_like_heading(text: str) -> bool:
    stripped = text.strip()
    return (
        0 < len(stripped) <= 80
        and "\n" not in stripped
        and stripped[-1] not in ".!?,;:"
    )


def parse_text(data: str) -> NormalisedDoc:
    doc = NormalisedDoc(fmt="text")
    paragraphs = [p.strip() for p in data.split("\n\n")]
    ordinal = 0
    for para in paragraphs:
        if not para:
            continue
        kind = BlockKind.heading if _looks_like_heading(para) else BlockKind.paragraph
        doc.blocks.append(
            Block(
                kind=kind,
                text=para,
                ordinal=ordinal,
                level=1 if kind == BlockKind.heading else None,
            )
        )
        ordinal += 1
    return doc
