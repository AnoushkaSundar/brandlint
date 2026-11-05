"""Stands in for /governance until the real governance agent lands."""

from fastapi import APIRouter

from mocks import data

router = APIRouter(prefix="/governance", tags=["mock governance"])


def _span(chunk_id: str, phrase: str) -> dict:
    start = data.chunks_for_piece("agency-blog")[chunk_id].index(phrase)
    return {"chunk_id": chunk_id, "start": start, "end": start + len(phrase)}


def proposals() -> list[dict]:
    return [
        {
            "id": "prop-demo-1",
            "rule_id": "R-TONE-02",
            "kind": "amendment",
            "current": (
                "Stay calm and helpful. Do not use fear, pressure or false urgency "
                "to persuade the reader."
            ),
            "suggested": (
                "Stay calm and helpful. Do not use fear, pressure or false urgency "
                "to persuade the reader. Describing a real risk factually is allowed."
            ),
            "evidence": {
                "count": 4,
                "examples": [_span("blog-p1", "quietly start looking elsewhere")],
            },
            "eval": {"passed": True, "precision": 0.94, "recall": 0.91},
            "status": "pending",
        },
        {
            "id": "prop-demo-2",
            "rule_id": "R-TERM-03",
            "kind": "term",
            "current": "Say new hire, never newbie or fresher.",
            "suggested": (
                "Say new hire, never newbie or fresher, except in direct quotes."
            ),
            "evidence": {"count": 3, "examples": [_span("blog-p1", "newbies")]},
            "eval": {"passed": True, "precision": 0.96, "recall": 0.9},
            "status": "pending",
        },
    ]


@router.post("/run")
def run() -> list[dict]:
    return proposals()


@router.get("/spot-checks")
def spot_checks() -> list[dict]:
    return [{"content_id": "cnt-demo-case-study", "review_id": "rev-demo-case-study"}]
