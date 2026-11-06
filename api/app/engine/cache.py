"""The verdict cache: one row per chunk x rule.

It stores the model's validated answer, not the final verdict, so the checks that
run after the model (control word, injection detectors) still apply on a hit.
Only usable answers go in, so an outage or a bad reply is never remembered.

A hit counts only if every fact it depended on is unchanged and the time is before
`valid_until`, the earliest expiry among those facts.

The cache only saves calls. A database error here counts as a miss, so the model
answers and the review carries on.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.engine import models

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


def cache_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime) -> datetime:
    """SQLite drops the time zone that Postgres keeps."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


class VerdictCache:
    def __init__(
        self, session_factory: Callable[[], Session], *, now: Clock = _utc_now
    ) -> None:
        self._session_factory = session_factory
        self._now = now

    def get(self, key: str, facts: Mapping[str, int]) -> dict | None:
        """The stored answer, if it's still valid. `facts` maps id to current version."""
        try:
            with self._session_factory() as session:
                row = session.scalar(
                    select(models.ReviewCache).where(
                        models.ReviewCache.cache_key == key
                    )
                )
        except SQLAlchemyError:
            logger.warning("verdict cache read failed", exc_info=True)
            return None
        if row is None:
            return None
        if row.valid_until is not None and self._now() >= _aware(row.valid_until):
            return None
        for dependency in row.depends_on:
            if facts.get(dependency["fact_id"]) != dependency["version"]:
                return None
        return row.payload

    def put(
        self,
        key: str,
        *,
        unit_type: str,
        verdict: str,
        payload: dict,
        manifest: dict,
        depends_on: list[dict] | None = None,
        valid_until: datetime | None = None,
    ) -> None:
        row = models.ReviewCache(
            id=str(uuid.uuid4()),
            cache_key=key,
            unit_type=unit_type,
            verdict=verdict,
            payload=payload,
            depends_on=depends_on or [],
            valid_until=valid_until,
            manifest=manifest,
        )
        try:
            with self._session_factory() as session:
                existing = session.scalar(
                    select(models.ReviewCache).where(
                        models.ReviewCache.cache_key == key
                    )
                )
                if existing is not None:
                    # A stale row is replaced; a valid one would have been a hit.
                    session.delete(existing)
                    session.flush()
                session.add(row)
                try:
                    session.commit()
                except IntegrityError:
                    # A parallel review stored the same answer first.
                    session.rollback()
        except SQLAlchemyError:
            logger.warning("verdict cache write failed", exc_info=True)
