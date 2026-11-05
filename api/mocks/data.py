"""Loads the demo brand. Every mock answers from this data, so they stay consistent."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

PIECES = ("agency-blog", "linkedin-post", "banner")


def demo_dir() -> Path:
    default = Path(__file__).resolve().parents[2] / "demo"
    return Path(os.environ.get("DEMO_DIR", default))


def _load(*parts: str) -> Any:
    return json.loads(demo_dir().joinpath(*parts).read_text(encoding="utf-8"))


@lru_cache
def findings_for_piece(piece: str) -> list[dict]:
    return _load("findings", f"{piece}.json")


@lru_cache
def chunks_for_piece(piece: str) -> dict[str, str]:
    chunks = _load("pieces", f"{piece}.chunks.json")
    return {chunk["chunk_id"]: chunk["text"] for chunk in chunks}


@lru_cache
def rules() -> list[dict]:
    return _load("brand", "rules.json")


def piece_for_review(review_id: str) -> str | None:
    piece = review_id.removeprefix("rev-demo-")
    return piece if piece in PIECES else None


def find_finding(finding_id: str) -> tuple[str, dict] | None:
    for piece in PIECES:
        for finding in findings_for_piece(piece):
            if finding["id"] == finding_id:
                return piece, finding
    return None
