"""CI activity for the insights view: how many runs, how they ended, how long they took, why
they failed and which tokens are in use. Counts only: no draft text, no person."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from sqlalchemy.orm import Session

from app.auth.defaults import utc_now
from app.ci.models import CIRun, ServiceToken
from app.tenancy import scoped


def _aware(moment):
    return moment if moment.tzinfo else moment.replace(tzinfo=utc_now().tzinfo)


def summary(session: Session) -> dict:
    now = utc_now()
    week, month = now - timedelta(days=7), now - timedelta(days=30)
    runs = list(session.scalars(scoped(session, CIRun).order_by(CIRun.created_at.desc()).limit(5000)))
    recent = [run for run in runs if _aware(run.created_at) >= month]
    by_result = Counter(run.result or ("error" if run.state == "error" else "running") for run in recent)
    seconds = [
        (_aware(run.finished_at) - _aware(run.created_at)).total_seconds()
        for run in recent
        if run.finished_at is not None
    ]
    # Why runs errored. A failed run's first reason only says "N findings block this run".
    reasons = Counter(
        (run.reasons or ["No reason given."])[0] for run in recent if run.state == "error"
    )
    per_token = Counter(run.token_id for run in runs if run.token_id and _aware(run.created_at) >= week)
    tokens = [
        {
            "name": token.name,
            "prefix": token.prefix,
            "runs_7d": per_token.get(token.id, 0),
            "last_used_at": token.last_used_at,
            "revoked": token.revoked_at is not None,
        }
        for token in session.scalars(scoped(session, ServiceToken).order_by(ServiceToken.created_at.desc()))
    ]
    return {
        "runs_30d": len(recent),
        "runs_7d": sum(1 for run in recent if _aware(run.created_at) >= week),
        "by_result": {key: by_result.get(key, 0) for key in ("pass", "fail", "error", "running")},
        "average_seconds": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "failure_reasons": [{"reason": reason, "count": count} for reason, count in reasons.most_common(5)],
        "tokens": tokens,
    }
