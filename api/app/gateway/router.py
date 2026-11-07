"""Gateway router. These routes exist only while USE_MOCK_GATEWAY is false;
otherwise they would collide with the mock mounted at the same paths.

`{review_id}` is the engine's review id, as on /engine/reviews/{id}/findings.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import CurrentUser, SessionDep, current_user
from app.clients.flags import use_mock
from app.engine.access import require_review
from app.gateway import disclosure

MASKING_DOWN = "Masking is unavailable, so nothing can be shown"


def _review_routes() -> APIRouter:
    routes = APIRouter(dependencies=[Depends(current_user)])

    @routes.get("/reviews/{review_id}/disclosure")
    def review_disclosure(review_id: str, user: CurrentUser, session: SessionDep) -> dict:
        require_review(review_id, user, session)
        try:
            return disclosure.disclosure(review_id, session)
        except httpx.HTTPError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, MASKING_DOWN) from None

    @routes.get("/reviews/{review_id}/masking-preview")
    def review_masking_preview(
        review_id: str, user: CurrentUser, session: SessionDep
    ) -> dict:
        require_review(review_id, user, session)
        try:
            return disclosure.masking_preview(review_id, session)
        except httpx.HTTPError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, MASKING_DOWN) from None

    return routes


def build_router() -> APIRouter:
    built = APIRouter(prefix="/gateway", tags=["gateway"])
    if not use_mock("GATEWAY"):
        built.include_router(_review_routes())
    return built


router = build_router()
