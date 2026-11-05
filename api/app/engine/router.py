"""Engine router. Real endpoints (POST /engine/reviews, the SSE findings stream,
fix, replay, recheck, eval gate) are added here in later blocks. For now it
carries a health check so router auto-discovery has a concrete target.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/engine", tags=["engine"])


@router.get("/health")
def engine_health() -> dict[str, str]:
    return {"status": "ok", "service": "engine"}
