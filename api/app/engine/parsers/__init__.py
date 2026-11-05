"""Parsers: raw content (str or bytes) + format -> NormalisedDoc.

Heavy-format parsers (docx, pdf, image) are imported lazily so importing this
package costs nothing and tests that only touch text/html don't need the libs.
"""

from __future__ import annotations

import unicodedata

from app.engine.parsers.base import Block, BlockKind, NormalisedDoc, Style
from app.engine.parsers.html import parse_html
from app.engine.parsers.text import parse_text

_TEXT_FORMATS = {"text", "txt", "md", "markdown"}
_HTML_FORMATS = {"html", "htm"}
_IMAGE_FORMATS = {"image", "png", "jpg", "jpeg", "webp", "tiff"}


def _as_str(data: str | bytes) -> str:
    return data if isinstance(data, str) else data.decode("utf-8")


def _as_bytes(data: str | bytes) -> bytes:
    return data if isinstance(data, bytes) else data.encode("utf-8")


def _normalise(doc: NormalisedDoc) -> NormalisedDoc:
    """NFKC-normalise all text so ligatures (``ﬁ`` -> ``fi``) and other glyphs
    that PDF/DOCX extraction emits compare equal to the rulebook's plain text."""
    for block in doc.blocks:
        block.text = unicodedata.normalize("NFKC", block.text)
    doc.meta = {
        k: (unicodedata.normalize("NFKC", v) if isinstance(v, str) else v)
        for k, v in doc.meta.items()
    }
    return doc


def _dispatch(data: str | bytes, fmt: str, **opts) -> NormalisedDoc:
    if fmt in _TEXT_FORMATS:
        return parse_text(_as_str(data))
    if fmt in _HTML_FORMATS:
        return parse_html(_as_str(data))
    if fmt == "docx":
        from app.engine.parsers.docx_parser import parse_docx

        return parse_docx(_as_bytes(data))
    if fmt == "pdf":
        from app.engine.parsers.pdf_parser import parse_pdf

        return parse_pdf(_as_bytes(data))
    if fmt in _IMAGE_FORMATS:
        from app.engine.parsers.image_parser import parse_image

        return parse_image(_as_bytes(data), **opts)
    raise ValueError(f"unsupported format: {fmt!r}")


def parse(data: str | bytes, fmt: str, **opts) -> NormalisedDoc:
    """Dispatch to the right parser and NFKC-normalise the result. ``fmt`` is a
    format/extension string."""
    return _normalise(_dispatch(data, fmt.lower().lstrip("."), **opts))


__all__ = [
    "Block",
    "BlockKind",
    "NormalisedDoc",
    "Style",
    "parse",
    "parse_html",
    "parse_text",
]
