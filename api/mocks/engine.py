"""Stands in for /engine until the real review engine lands."""

import asyncio
import json
import os
from collections import Counter
from collections.abc import AsyncIterator
from hashlib import sha256

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mocks import data

MAX_FIX_ATTEMPTS = 2
NO_SAFE_FIX = "No safe fix found; marked for review"

# Any other channel falls back to the blog, which has the fullest set of findings.
PIECE_BY_CHANNEL = {"linkedin": "linkedin-post", "banner": "banner"}
DEFAULT_PIECE = "agency-blog"

# Canned rewrites of the last span in each finding.
FIXES = {
    "fnd-agency-blog-01": "Tarnhollow Landing",
    "fnd-agency-blog-02": "trusted",
    "fnd-agency-blog-03": "new hires",
    "fnd-agency-blog-06": "by 38%",
    "fnd-linkedin-post-02": "designed to help new hires settle in",
    "fnd-linkedin-post-03": (
        "A good first week shapes how people feel about a new job, and it's "
        "worth getting right."
    ),
    "fnd-linkedin-post-04": "Results vary by organisation.",
}

router = APIRouter(prefix="/engine", tags=["mock engine"])
_fix_attempts: Counter[str] = Counter()


class ReviewRequest(BaseModel):
    content_version_id: str
    channel: str
    rulebook_version: int


class RecheckRequest(BaseModel):
    changed_chunk_ids: list[str]


class EvalGateRequest(BaseModel):
    proposal: dict


def reset() -> None:
    _fix_attempts.clear()


def _delay() -> float:
    return float(os.environ.get("MOCK_STREAM_DELAY", "0.5"))


def _event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


async def _stream(findings: list[dict]) -> AsyncIterator[str]:
    """Sends code findings at once and AI findings after a delay, as the engine will."""
    for finding in sorted(findings, key=lambda item: item["tier"]):
        if finding["tier"] > 0:
            await asyncio.sleep(_delay())
        yield _event("finding", finding)
    yield _event("done", {"count": len(findings)})


def _event_stream(findings: list[dict]) -> StreamingResponse:
    return StreamingResponse(_stream(findings), media_type="text/event-stream")


def _findings_for_review(review_id: str) -> list[dict]:
    piece = data.piece_for_review(review_id)
    if piece is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    return data.findings_for_piece(piece)


def review_findings(review_id: str) -> list[dict]:
    return _findings_for_review(review_id)


def _require_finding(finding_id: str) -> tuple[str, dict]:
    match = data.find_finding(finding_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return match


def start_review(channel: str) -> dict:
    piece = PIECE_BY_CHANNEL.get(channel, DEFAULT_PIECE)
    return {"review_id": f"rev-demo-{piece}"}


@router.post("/reviews")
def post_review(body: ReviewRequest) -> dict:
    return start_review(body.channel)


def _chunk_style(chunk_id: str) -> dict | None:
    if chunk_id.endswith("-hidden"):
        return {"hidden": True}
    return {"from_ocr": True} if "-ocr-" in chunk_id else None


def _chunk_kind(chunk_id: str) -> str:
    if chunk_id.endswith("-h1"):
        return "heading"
    return "image" if chunk_id.endswith("-image") else "paragraph"


@router.get("/reviews/{review_id}/chunks")
def list_chunks(review_id: str) -> list[dict]:
    """Returns the contract's Chunk shape, which the review screen highlights from."""
    piece = data.piece_for_review(review_id)
    if piece is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    return [
        {
            "id": chunk_id,
            "content_version_id": f"cv-demo-{piece}-1",
            "ordinal": ordinal,
            "kind": _chunk_kind(chunk_id),
            "text": text,
            "content_hash": sha256(text.encode()).hexdigest(),
            "data_class": "public",
            "style": _chunk_style(chunk_id),
        }
        for ordinal, (chunk_id, text) in enumerate(data.chunks_for_piece(piece).items())
    ]


@router.get("/reviews/{review_id}/findings")
def stream_findings(review_id: str) -> StreamingResponse:
    return _event_stream(_findings_for_review(review_id))


@router.post("/reviews/{review_id}/recheck")
def recheck(review_id: str, body: RecheckRequest) -> StreamingResponse:
    changed = set(body.changed_chunk_ids)
    return _event_stream(
        [
            finding
            for finding in _findings_for_review(review_id)
            if changed & {span["chunk_id"] for span in finding["spans"]}
        ]
    )


def suggest_fix(finding_id: str, attempt: int) -> dict:
    piece, finding = _require_finding(finding_id)
    if not finding["fix_available"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "No fix is available")

    span = finding["spans"][-1]
    text = data.chunks_for_piece(piece)[span["chunk_id"]]
    original = text[span["start"] : span["end"]]
    suggested = FIXES[finding_id]
    return {
        "finding_id": finding_id,
        "original": original,
        "suggested": suggested,
        "diff": f"- {original}\n+ {suggested}",
        "attempt": attempt,
    }


@router.post("/findings/{finding_id}/fix")
def request_fix(finding_id: str) -> dict:
    _require_finding(finding_id)
    attempt = _fix_attempts[finding_id] + 1
    if attempt > MAX_FIX_ATTEMPTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, NO_SAFE_FIX)
    suggestion = suggest_fix(finding_id, attempt)
    _fix_attempts[finding_id] = attempt
    return suggestion


@router.post("/verdicts/{finding_id}/replay")
def replay(finding_id: str) -> dict:
    _, finding = _require_finding(finding_id)
    return {
        "identical": True,
        "verdict": finding["verdict"],
        "manifest": {
            "rule_id": finding["rule_id"],
            "rule_version": finding["rule_version"],
            "fact_ids": finding["fact_ids"],
            "models": finding["models_used"],
            "as_of": "2026-11-07",
        },
    }


@router.post("/eval/gate")
def eval_gate(body: EvalGateRequest) -> dict:
    return {"passed": True, "precision": 0.94, "recall": 0.91}
