"""Spot-checks: a sample of passed content for a reviewer, our only source of
missed-issue labels.

The draw hashes the content id, so asking again can't slowly sample everything.
A small library still gets one item, or the queue would never have anything in it.
"""

from __future__ import annotations

import hashlib
import os
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.models import Content
from app.contracts import ContentState
from app.governance.models import SpotCheck
from app.memory.edges import latest_reviews


def _rate() -> float:
    return float(os.getenv("SPOT_CHECK_RATE", "0.05"))


def _drawn(content_id: str, rate: float) -> bool:
    digest = hashlib.sha256(content_id.encode()).digest()
    return int.from_bytes(digest[:8]) / 2**64 < rate


def sample(session: Session) -> list[dict[str, str]]:
    latest = latest_reviews(session)
    published = session.scalars(
        select(Content.id)
        .where(Content.state == ContentState.published.value)
        .order_by(Content.created_at)
    ).all()
    candidates = [content_id for content_id in published if content_id in latest]
    sampled = set(session.scalars(select(SpotCheck.content_id)))
    rate = _rate()
    chosen = [c for c in candidates if _drawn(c, rate)] or candidates[:1]
    for content_id in chosen:
        if content_id not in sampled:
            session.add(
                SpotCheck(
                    id=str(uuid.uuid4()), content_id=content_id,
                    review_id=latest[content_id],
                )
            )
    session.commit()
    rows = session.scalars(select(SpotCheck).order_by(SpotCheck.sampled_at)).all()
    return [{"content_id": row.content_id, "review_id": row.review_id} for row in rows]
