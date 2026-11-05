from fastapi import APIRouter, Depends
from mocks import engine, gateway, governance, memory

from app.auth.dependencies import current_user
from app.clients.flags import use_mock


def build_router() -> APIRouter:
    """Serves the mocks at their contract paths while each service's flag is on."""
    mounted = APIRouter(dependencies=[Depends(current_user)])
    if use_mock("ENGINE"):
        mounted.include_router(engine.router)
        mounted.include_router(governance.router)
    if use_mock("GATEWAY"):
        mounted.include_router(gateway.router)
    if use_mock("MEMORY"):
        mounted.include_router(memory.router)
    return mounted


router = build_router()
