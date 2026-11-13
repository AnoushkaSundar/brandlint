"""Quotas for sandbox workspaces, so a visitor (or a script) can't run up the bill.

A sandbox org has a cap on people, pieces of content, upload size, reviews per day and
model calls per day. The Tarnhollow demo org has none, and neither does an org this
module can't find. Going over a cap is a 429 with a message that says which one.

Every cap can be changed with an environment variable, named below.
"""

from __future__ import annotations

import os
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.defaults import utc_now
from app.auth.models import Organization, User
from app.tenancy import resolve_org, scoped


def _cap(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def caps() -> dict[str, int]:
    return {
        "users": _cap("SANDBOX_MAX_USERS", 10),
        "content": _cap("SANDBOX_MAX_CONTENT", 50),
        "upload_bytes": _cap("SANDBOX_MAX_UPLOAD_BYTES", 2 * 1024 * 1024),
        "reviews_per_day": _cap("SANDBOX_MAX_REVIEWS_PER_DAY", 20),
        "llm_calls_per_day": _cap("SANDBOX_MAX_LLM_CALLS_PER_DAY", 300),
    }


def is_sandbox(session: Session) -> bool:
    # organizations is the one shared table, so it is read directly.
    org = session.get(Organization, str(resolve_org(session)))
    return org is not None and org.kind == "sandbox"


def over(message: str) -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)


def check_users(session: Session) -> None:
    if not is_sandbox(session):
        return
    limit = caps()["users"]
    from app.ci.runs import not_a_ci_person

    # The CI service user isn't a person, so it doesn't use up a place.
    if session.scalar(scoped(session, User, func.count()).where(not_a_ci_person())) >= limit:
        raise over(f"This workspace is limited to {limit} people.")


def check_content(session: Session) -> None:
    from app.content.models import Content

    if not is_sandbox(session):
        return
    limit = caps()["content"]
    if session.scalar(scoped(session, Content, func.count())) >= limit:
        raise over(f"This workspace is limited to {limit} pieces of content.")


def check_upload_size(session: Session, size: int) -> None:
    if is_sandbox(session) and size > caps()["upload_bytes"]:
        megabytes = caps()["upload_bytes"] / (1024 * 1024)
        raise over(f"Files in this workspace can be up to {megabytes:g} MB.")


def check_reviews_today(session: Session) -> None:
    from app.workflow.models import Review

    if not is_sandbox(session):
        return
    limit = caps()["reviews_per_day"]
    since = utc_now() - timedelta(days=1)
    started = session.scalar(
        scoped(session, Review, func.count()).where(Review.created_at >= since)
    )
    if started >= limit:
        raise over(f"This workspace is limited to {limit} reviews a day.")
