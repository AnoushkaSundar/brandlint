"""BrandLint FastAPI application.

Routers are AUTO-DISCOVERED: every ``api/app/**/router.py`` that defines a
module-level ``router`` (an ``APIRouter``) is included automatically. Do NOT
edit this file to add an endpoint — add a ``router.py`` in your own package.

Shared file: written once in block 2; both owners approve. Uvicorn entry point
is ``app.main:app``.
"""

from __future__ import annotations

import importlib
import os
import pkgutil

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

# The browser calls the API cross-origin (web on :3000 -> api on :8000), so CORS
# must be configured on the app. A router can't add middleware and main.py is
# written once, so it lives here. Can't be "*" while credentials are allowed.
WEB_ORIGIN = os.getenv("WEB_ORIGIN", "http://localhost:3000")


def discover_routers() -> list[APIRouter]:
    """Import every ``app.**.router`` module and collect its ``router``."""
    package = importlib.import_module("app")
    found: list[APIRouter] = []
    for module_info in pkgutil.walk_packages(package.__path__, prefix="app."):
        if not module_info.name.endswith(".router"):
            continue
        module = importlib.import_module(module_info.name)
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            found.append(router)
    return found


def create_app() -> FastAPI:
    application = FastAPI(title="BrandLint API", version="0.1")

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[WEB_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in discover_routers():
        application.include_router(router)
    return application


app = create_app()
