"""The AI gateway — the ONLY place in the codebase that reaches a model.

`call()` is the single entry point every component uses. Provider keys live
only in the LiteLLM proxy; here we talk to that proxy over plain HTTP (httpx),
never a provider SDK, so the CI import guard stays satisfied.

It routes by data class, masks what leaves, calls the pinned model through the
proxy at temperature 0, restores tokens in the reply, and logs every call to
`gateway_log`. Restricted data is refused until its local route lands in block 8.
The policy engine and leak checks land in later blocks, as marked below.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from app.contracts import DataClass
from app.gateway import masking
from app.gateway.models import GatewayLog

# Pinned per review. The concrete model is pinned again in the LiteLLM config;
# this is the logical name the proxy maps to a provider.
PINNED_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5")
LITELLM_URL = os.getenv("LITELLM_URL", "http://localhost:4000")
LITELLM_KEY = os.getenv("LITELLM_MASTER_KEY", "")
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "30"))
# Part of the verdict cache key. Bump it when routing or masking rules change.
POLICY_VERSION = "policy-1"


def _route(data_class: DataClass) -> str:
    """Policy stub. Restricted data goes to the local model group ("ollama"),
    which lands in block 8. Everything else goes out masked.

    The full data-class x provider x purpose policy engine lands in block 7.
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
    session: Any,
    review_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Single entry point for every model call.

    Args:
        purpose: why we're calling (e.g. "classify", "fix", "governance").
        data_class: public | internal | confidential | restricted.
        rule_ids: rules this call serves (for logging/audit).
        payload: request body; must carry OpenAI-style ``messages``.
        session: SQLAlchemy session to log into (gateway_log). REQUIRED — every
            call must be logged; the disclosure panel and audit log depend on it.
        review_id: optional link to the review for the disclosure panel.
        model: override the pinned model (tests/experiments only).

    Returns the model's parsed output as a dict (matching the requested schema,
    like the mock) — not the raw proxy envelope. Raises on transport/route
    errors; the call is logged either way.
    """
    if session is None:
        raise ValueError(
            "session is required: every gateway call must be logged to gateway_log"
        )
    dc = DataClass(data_class)
    model = model or PINNED_MODEL
    route = _route(dc)
    started = time.perf_counter()
    status = "ok"
    provider: str | None = None
    error: str | None = None
    masked: masking.Masked | None = None

    try:
        if route != "litellm":
            raise NotImplementedError(
                f"{dc.value} data is not sent out (route={route}); the local route "
                f"lands in block 8"
            )
        masked = masking.mask_messages(
            payload["messages"],
            data_class=dc,
            # Without a review, tokens only need to last for this call.
            scope=review_id or f"call-{uuid.uuid4()}",
            bind=session.get_bind(),
        )
        body = {
            "model": model,
            "temperature": 0,  # deterministic: tier-1 verdicts must be reproducible
            "messages": masked.messages,
        }
        raw = _chat_completion(body)
        # (block 8) leak-check the response here.
        provider = raw.get("model")
        # Return the parsed model output, matching the mock's schema-shaped dict.
        content = raw["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            parsed = {"content": content}
        return masking.unmask(parsed, masked.tokens)
    except Exception as exc:
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        session.add(
            GatewayLog(
                id=str(uuid.uuid4()),
                purpose=purpose,
                data_class=dc.value,
                rule_ids=list(rule_ids or []),
                provider=provider,
                model=model,
                route=route,
                masked=dict(masked.counts) if masked and masked.counts else None,
                review_id=review_id,
                status=status,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=error,
            )
        )
        session.flush()
