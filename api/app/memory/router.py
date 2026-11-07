"""Memory router. These routes exist only while USE_MOCK_MEMORY is false;
otherwise they would collide with the mock mounted at the same paths.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import SessionDep, current_user, require_roles
from app.clients.flags import use_mock
from app.contracts import Precedent, Role
from app.memory import queries

# Impact and the graph span every piece, and creators include outside agencies.
STAFF = require_roles(Role.reviewer, Role.manager, Role.legal, Role.admin)


def _routes() -> APIRouter:
    routes = APIRouter(dependencies=[Depends(current_user)])

    @routes.get("/impact", dependencies=[Depends(STAFF)])
    def impact(fact_id: str, session: SessionDep) -> list[dict]:
        return queries.impact(fact_id, session)

    @routes.get("/precedents", response_model=list[Precedent])
    def precedents(finding_id: str, session: SessionDep) -> list[Precedent]:
        return queries.precedents(finding_id, session)

    @routes.get("/graph", dependencies=[Depends(STAFF)])
    def graph(root: str, session: SessionDep) -> dict:
        return queries.graph(root, session)

    return routes


def build_router() -> APIRouter:
    built = APIRouter(prefix="/memory", tags=["memory"])
    if not use_mock("MEMORY"):
        built.include_router(_routes())
    return built


router = build_router()
