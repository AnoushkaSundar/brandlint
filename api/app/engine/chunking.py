"""Chunking: turn a NormalisedDoc into content-hashed chunks.

- **id**: ``{content_version_id}:{ordinal}`` — deterministic within a version
  (a given parse always yields the same ids), and unique in the `chunks` table.
  It is **not** stable across versions, because each version has its own id.
- **content_hash**: SHA-256 of the block text. Incremental re-review relies on
  THIS, not on id stability: a new version's chunk whose hash matches a cached
  verdict reuses it, and only hash-changed chunks are re-checked (verdict cache,
  block 5). Chunks are mapped across versions by ordinal.

Produces lightweight ``ParsedChunk`` dataclasses whose ``as_dict()`` matches the
columns of the ``chunks`` table; the orchestration layer maps them to the ORM.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.engine.parsers.base import NormalisedDoc


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ParsedChunk:
    id: str
    content_version_id: str
    ordinal: int
    kind: str
    text: str
    content_hash: str
    data_class: str
    style: dict | None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "content_version_id": self.content_version_id,
            "ordinal": self.ordinal,
            "kind": self.kind,
            "text": self.text,
            "content_hash": self.content_hash,
            "data_class": self.data_class,
            "style": self.style,
        }


def chunk_document(
    doc: NormalisedDoc,
    content_version_id: str,
    *,
    data_class: str = "public",
) -> list[ParsedChunk]:
    """One chunk per block (headings, paragraphs, and image/OCR blocks)."""
    chunks: list[ParsedChunk] = []
    for block in doc.blocks:
        chunks.append(
            ParsedChunk(
                id=f"{content_version_id}:{block.ordinal}",
                content_version_id=content_version_id,
                ordinal=block.ordinal,
                kind=block.kind.value,
                text=block.text,
                content_hash=sha256_text(block.text),
                data_class=data_class,
                style=block.style.as_dict(),
            )
        )
    return chunks
