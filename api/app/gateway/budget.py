"""A daily cap on model calls for a sandbox workspace, counted from gateway_log.

The demo org and any org this can't find have no cap. `llm.call` refuses the call when the
cap is reached, and the API checks it before starting a review, so the visitor is told
early. Set SANDBOX_MAX_LLM_CALLS_PER_DAY to change it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.gateway.models import GatewayLog
from app.tenancy import resolve_org, scoped


class BudgetExceeded(Exception):
    """The workspace has used its model calls for today."""


def daily_cap() -> int:
    return int(os.getenv("SANDBOX_MAX_LLM_CALLS_PER_DAY", "300"))


def check(session: Session) -> None:
    """Raises BudgetExceeded when a sandbox org has used its calls for the last 24 hours."""
    from app.auth.models import Organization

    org = session.get(Organization, str(resolve_org(session)))
    if org is None or org.kind != "sandbox":
        return
    since = datetime.now(UTC) - timedelta(days=1)
    used = session.scalar(
        scoped(session, GatewayLog, func.count()).where(
            GatewayLog.created_at >= since, GatewayLog.route == "litellm"
        )
    )
    if used >= daily_cap():
        raise BudgetExceeded(
            f"This workspace has used its {daily_cap()} model calls for today."
        )
