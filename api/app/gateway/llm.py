"""The AI gateway — the ONLY place in the codebase that reaches a model.

`call()` is the single entry point every component uses. Provider keys live
only in the LiteLLM proxy; here we talk to that proxy over plain HTTP (httpx),
never a provider SDK, so the CI import guard stays satisfied.

`policy.py` decides what each data class may do. This masks what leaves, calls
the pinned model through the proxy at temperature 0, checks the reply for leaks,
restores tokens in it, and logs every call to `gateway_log`. Restricted data
stays on the local model group, and is refused if that isn't running.
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
from app.gateway import masking, policy
from app.gateway.models import GatewayLog
from app.gateway.policy import PINNED_MODEL, POLICY_VERSION

__all__ = ["PINNED_MODEL", "POLICY_VERSION", "LeakBlocked", "PolicyBlocked", "call"]

LITELLM_URL = os.getenv("LITELLM_URL", "http://localhost:4000")
LITELLM_KEY = os.getenv("LITELLM_MASTER_KEY", "")
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "30"))


class PolicyBlocked(Exception):
    """The policy table doesn't allow this call."""


class LeakBlocked(Exception):
    """The reply held something the model was never given."""


def _route(data_class: DataClass, purpose: str, model: str) -> str:
    if policy.stays_local(data_class, purpose):
        return "ollama"
    provider = policy.provider_of(model)
    if policy.decide(data_class, purpose, provider) == policy.Action.block:
        return "blocked"
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


def _parse_output(content: Any) -> Any:
    """The model's JSON, even inside a code fence or followed by commentary, which
    is how it answers when it has nothing to report. Anything else stays as text."""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass
    text = str(content)
    start = text.find("{")
    if start >= 0:
        try:
            return json.JSONDecoder().raw_decode(text, start)[0]
        except json.JSONDecodeError:
            pass
    return {"content": content}


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
    route = _route(dc, purpose, model or PINNED_MODEL)
    model = policy.LOCAL_MODEL if route == "ollama" else model or PINNED_MODEL
    started = time.perf_counter()
    status = "ok"
    provider: str | None = None
    error: str | None = None
    masked: masking.Masked | None = None

    try:
        if route == "blocked":
            raise PolicyBlocked(f"{dc.value} data may not be used for {purpose}")
        if route == "litellm":
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
            "messages": masked.messages if masked else payload["messages"],
        }
        raw = _chat_completion(body)
        provider = raw.get("model")
        # Return the parsed model output, matching the mock's schema-shaped dict.
        content = raw["choices"][0]["message"]["content"]
        if masked:
            problem = masking.leak(
                content, masked.tokens, masking.deny_list(session.get_bind())
            )
            if problem:
                raise LeakBlocked(problem)
        parsed = _parse_output(content)
        return masking.unmask(parsed, masked.tokens) if masked else parsed
    except (PolicyBlocked, LeakBlocked) as exc:
        status = "blocked"
        error = f"{type(exc).__name__}: {exc}"
        raise
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
