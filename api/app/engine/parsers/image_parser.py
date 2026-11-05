"""Image parser (Tesseract OCR via pytesseract). Produces a single image block
whose text is the OCR output, flagged ``from_ocr`` so the hidden-content check
can compare it against the visible copy. Needs the ``tesseract-ocr`` binary.
"""

from __future__ import annotations

from io import BytesIO

from app.engine.parsers.base import Block, BlockKind, NormalisedDoc, Style


def parse_image(data: bytes, *, image_ref: str | None = None) -> NormalisedDoc:
    import pytesseract  # lazy
    from PIL import Image

    image = Image.open(BytesIO(data))
    text = pytesseract.image_to_string(image).strip()
    doc = NormalisedDoc(fmt="image")
    doc.blocks.append(
        Block(
            kind=BlockKind.image,
            text=text,
            ordinal=0,
            image_ref=image_ref,
            style=Style(from_ocr=True),
        )
    )
    return doc
