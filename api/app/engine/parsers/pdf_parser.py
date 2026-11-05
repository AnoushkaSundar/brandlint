"""PDF parser (PyMuPDF). Each text block becomes a paragraph, keeping the first
span's font size (pt) and colour for hidden-content checks.
"""

from __future__ import annotations

from app.engine.parsers.base import Block, BlockKind, NormalisedDoc, Style


def parse_pdf(data: bytes) -> NormalisedDoc:
    import pymupdf  # lazy

    pdf = pymupdf.open(stream=data, filetype="pdf")
    doc = NormalisedDoc(fmt="pdf")
    ordinal = 0
    try:
        for page in pdf:
            layout = page.get_text("dict")
            for block in layout.get("blocks", []):
                if block.get("type") != 0:  # 0 = text block
                    continue
                spans = [
                    span
                    for line in block.get("lines", [])
                    for span in line.get("spans", [])
                ]
                text = " ".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue
                first = spans[0] if spans else {}
                color_int = first.get("color")
                color = (
                    f"#{color_int:06x}" if isinstance(color_int, int) else None
                )
                doc.blocks.append(
                    Block(
                        kind=BlockKind.paragraph,
                        text=text,
                        ordinal=ordinal,
                        style=Style(color=color, font_pt=first.get("size")),
                    )
                )
                ordinal += 1
        meta = pdf.metadata or {}
        if meta.get("title"):
            doc.meta["title"] = meta["title"]
        if meta.get("author"):
            doc.meta["author"] = meta["author"]
    finally:
        pdf.close()
    return doc
