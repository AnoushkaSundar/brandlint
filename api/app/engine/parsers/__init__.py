"""Parsers: raw content (str or bytes) + format -> NormalisedDoc.

Heavy-format parsers (docx, pdf, image) are imported lazily so importing this
package costs nothing and tests that only touch text/html don't need the libs.
"""

from __future__ import annotations

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


def parse(data: str | bytes, fmt: str, **opts) -> NormalisedDoc:
    """Dispatch to the right parser. ``fmt`` is a format/extension string."""
    fmt = fmt.lower().lstrip(".")
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


__all__ = [
    "Block",
    "BlockKind",
    "NormalisedDoc",
    "Style",
    "parse",
    "parse_html",
    "parse_text",
]
