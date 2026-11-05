"""The AI gateway — the ONLY place in the codebase that reaches a model.

`call()` is the single entry point every component uses. Provider keys live
only in the LiteLLM proxy; here we talk to that proxy over plain HTTP (httpx),
never a provider SDK, so the CI import guard stays satisfied.

Block-2 scope is a STUB: it routes by data class, calls the pinned model
through the proxy at temperature 0, and logs every call to `gateway_log`.
Masking, the policy engine, leak checks and the Ollama/local route land in
later blocks (4, 7, 8) — the pipeline is shaped here with those as marked
extension points.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from app.contracts import DataClass
from app.gateway.models import GatewayLog

# Pinned per review. The concrete model is pinned again in the LiteLLM config;
# this is the logical name the proxy maps to a provider.
PINNED_MODEL = os.getenv("LLM_MODEL", "claude-haiku-5-5")
LITELLM_URL = os.getenv("LITELLM_URL", "http://localhost:4000")
LITELLM_KEY = os.getenv("LITELLM_MASTER_KEY", "")
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "30"))


def _route(data_class: DataClass) -> str:
    """Policy stub: restricted data must stay local; everything else goes to the
    proxy. The full data-class x provider x purpose policy engine lands in block 7.
    """
    if data_class == DataClass.restricted:
        return "ollama"
    return "litellm"


def _chat_completion(body: dict[str, Any]) -> dict[str, Any]:
    """Transport to the LiteLLM proxy (OpenAI-compatible). Isolated so tests can
    monkeypatch it and so the proxy stays the only key holder."""
    headers = {"Authorization": f"Bearer {LITELLM_KEY}"} if LITELLM_KEY else {}
    resp = httpx.post(
        f"{LITELLM_URL}/v1/chat/completions",
        json=body,
        headers=headers,
        timeout=TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def call(
    purpose: str,
    data_class: str | DataClass,
    rule_ids: Iterable[str],
    payload: Mapping[str, Any],
    *,
    session: Any = None,
    review_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Single entry point for every model call.

    Args:
        purpose: why we're calling (e.g. "classify", "fix", "governance").
        data_class: public | internal | confidential | restricted.
        rule_ids: rules this call serves (for logging/audit).
        payload: request body; must carry OpenAI-style ``messages``.
        session: SQLAlchemy session to log into (gateway_log). If None, no row
            is written — callers in production always pass one.
        review_id: optional link to the review for the disclosure panel.
        model: override the pinned model (tests/experiments only).

    Returns the raw proxy response dict. Raises on transport/route errors; the
    call is logged either way.
    """
    dc = DataClass(data_class)
    model = model or PINNED_MODEL
    route = _route(dc)
    started = time.perf_counter()
    status = "ok"
    provider: str | None = None
    error: str | None = None
    result: dict[str, Any] = {}

    try:
        if route == "ollama":
            # Restricted data never leaves the box. Local route lands in block 8.
            raise NotImplementedError(
                "restricted/local route not implemented in the block-2 gateway stub"
            )
        # (block 4) detect + mask payload here before it leaves.
        body = {
            "model": model,
            "temperature": 0,  # deterministic: tier-1 verdicts must be reproducible
            "messages": list(payload["messages"]),
        }
        result = _chat_completion(body)
        # (block 8) leak-check + unmask the response here.
        provider = result.get("model")
        return result
    except Exception as exc:
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if session is not None:
            session.add(
                GatewayLog(
                    id=str(uuid.uuid4()),
                    purpose=purpose,
                    data_class=dc.value,
                    rule_ids=list(rule_ids or []),
                    provider=provider,
                    model=model,
                    route=route,
                    review_id=review_id,
                    status=status,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error=error,
                )
            )
            session.flush()
