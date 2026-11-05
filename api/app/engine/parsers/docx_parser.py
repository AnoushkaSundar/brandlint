"""DOCX parser (python-docx). Heading vs paragraph from the paragraph style;
font size (pt) and run colour preserved for hidden-content checks; title/author
from core properties.
"""

from __future__ import annotations

from io import BytesIO

from app.engine.parsers.base import Block, BlockKind, NormalisedDoc, Style


def _run_color(run) -> str | None:
    try:
        rgb = run.font.color.rgb
    except (AttributeError, KeyError):
        return None
    return f"#{rgb}" if rgb is not None else None


def parse_docx(data: bytes) -> NormalisedDoc:
    import docx  # lazy: only needed for this format

    document = docx.Document(BytesIO(data))
    doc = NormalisedDoc(fmt="docx")
    ordinal = 0
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = (para.style.name if para.style else "").lower()
        is_heading = style_name.startswith("heading") or style_name == "title"

        font_pt = None
        color = None
        for run in para.runs:
            if font_pt is None and run.font.size is not None:
                font_pt = run.font.size.pt
            if color is None:
                color = _run_color(run)
            if font_pt is not None and color is not None:
                break

        level = None
        if is_heading:
            digits = "".join(c for c in style_name if c.isdigit())
            level = int(digits) if digits else 1

        doc.blocks.append(
            Block(
                kind=BlockKind.heading if is_heading else BlockKind.paragraph,
                text=text,
                ordinal=ordinal,
                level=level,
                style=Style(color=color, font_pt=font_pt),
            )
        )
        ordinal += 1

    props = document.core_properties
    if props.title:
        doc.meta["title"] = props.title
    if props.author:
        doc.meta["author"] = props.author
    return doc
