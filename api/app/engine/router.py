"""Engine router. The review routes exist only while USE_MOCK_ENGINE is false;
otherwise they would collide with the mock mounted at the same paths.

A real review starts through `app.clients.engine.start_review`, so there is no
POST /engine/reviews here: content is handed over in-process (contracts/v3).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.admin.rulebook import rulebook_at
from app.auth.dependencies import CurrentUser, SessionDep, current_user, require_roles
from app.clients.flags import use_mock
from app.contracts import Chunk, Proposal, Role
from app.db import get_sessionmaker
from app.engine import evaluation, graph, models, replay, reviews
from app.engine.access import require_review
from app.gateway import policy

POLL_S = 0.05


def _sse(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


async def _follow(run: reviews.ReviewRun) -> AsyncIterator[str]:
    """Replays everything so far, then follows the run until it ends."""
    sent = 0
    while True:
        finished = run.finished.is_set()
        while sent < len(run.events):
            yield _sse(*run.events[sent])
            sent += 1
        if finished:
            return
        await asyncio.sleep(POLL_S)


async def _replay(events: list[tuple[str, dict]]) -> AsyncIterator[str]:
    for name, payload in events:
        yield _sse(name, payload)


def _review_routes() -> APIRouter:
    routes = APIRouter(dependencies=[Depends(current_user)])

    @routes.get("/reviews/{review_id}/findings")
    def stream_findings(
        review_id: str, user: CurrentUser, session: SessionDep
    ) -> StreamingResponse:
        require_review(review_id, user, session)
        run = reviews.get_run(review_id)
        if run is not None:
            body = _follow(run)
        else:
            events = reviews.stored_events(review_id, session)
            if events is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
            body = _replay(events)
        return StreamingResponse(body, media_type="text/event-stream")

    @routes.get("/reviews/{review_id}/chunks", response_model=list[Chunk])
    async def list_chunks(
        review_id: str, user: CurrentUser, session: SessionDep
    ) -> list[dict]:
        require_review(review_id, user, session)
        run = reviews.get_run(review_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
        while run.chunks is None and not run.finished.is_set():
            await asyncio.sleep(POLL_S)
        return [chunk.as_dict() for chunk in run.chunks or []]

    @routes.post("/verdicts/{finding_id}/replay")
    def replay_verdict(finding_id: str, user: CurrentUser, session: SessionDep) -> dict:
        finding = session.get(models.Finding, finding_id)
        if finding is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
        require_review(finding.review_id, user, session)
        classify = graph.gateway_classify(get_sessionmaker())
        try:
            result = replay.replay(
                finding_id, session, classify,
                graph.gateway_classify(get_sessionmaker(), policy.SECOND_MODEL),
            )
        except replay.NotReplayable as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
        return result

    @routes.post("/eval/gate", dependencies=[Depends(require_roles(Role.admin))])
    def eval_gate(proposal: Proposal, session: SessionDep) -> dict:
        rule = next((r for r in rulebook_at(session) if r.id == proposal.rule_id), None)
        if rule is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
        classify = graph.gateway_classify(get_sessionmaker())
        return evaluation.gate(proposal, rule, session, classify, model=graph.PINNED_MODEL)

    return routes


def build_router() -> APIRouter:
    built = APIRouter(prefix="/engine", tags=["engine"])

    @built.get("/health")
    def engine_health() -> dict[str, str]:
        return {"status": "ok", "service": "engine"}

    if not use_mock("ENGINE"):
        built.include_router(_review_routes())
    return built


router = build_router()
