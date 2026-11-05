"""Normalised document model — the single shape every parser produces.

Parsers turn text / DOCX / PDF / HTML / images into a `NormalisedDoc`: an ordered
list of `Block`s (headings, paragraphs, image blocks). Style info (colour, font
size, background, zero-width/comment flags) is preserved per block so the tier-0
hidden-content checks can run on it. Chunking then turns blocks into stable,
content-hashed chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BlockKind(str, Enum):
    heading = "heading"
    paragraph = "paragraph"
    image = "image"


@dataclass
class Style:
    """Presentation facts a parser can recover, used by hidden-content checks.
    All optional — a parser fills what the format exposes.
    """

    color: str | None = None          # hex, e.g. "#ffffff"
    background: str | None = None      # hex of the effective background
    font_pt: float | None = None       # font size in points
    hidden: bool = False               # display:none / visibility:hidden / aria-hidden
    from_comment: bool = False         # text came from an HTML/XML comment
    from_metadata: bool = False        # alt text, title attr, doc metadata, etc.
    from_ocr: bool = False             # text recovered from an image via OCR

    def as_dict(self) -> dict:
        return {
            "color": self.color,
            "background": self.background,
            "font_pt": self.font_pt,
            "hidden": self.hidden,
            "from_comment": self.from_comment,
            "from_metadata": self.from_metadata,
            "from_ocr": self.from_ocr,
        }


@dataclass
class Block:
    kind: BlockKind
    text: str
    ordinal: int                       # position in document order
    level: int | None = None           # heading level (1-6) when kind == heading
    style: Style = field(default_factory=Style)
    image_ref: str | None = None       # for image blocks

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "text": self.text,
            "ordinal": self.ordinal,
            "level": self.level,
            "style": self.style.as_dict(),
            "image_ref": self.image_ref,
        }


@dataclass
class NormalisedDoc:
    blocks: list[Block] = field(default_factory=list)
    fmt: str = "text"                  # text | docx | pdf | html | image
    meta: dict = field(default_factory=dict)  # title, author, doc metadata, ...

    def text_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.kind != BlockKind.image]
