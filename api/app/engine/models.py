"""Engine table models (Alapan-owned): parsed chunks, extracted claim units,
findings, and the verdict cache.

Cross-owner ids (content_version_id, review_id) are stored as plain strings with
NO foreign key to Anoushka's tables — owners never couple to each other's schema;
they read across the API. See docs/contracts.md.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.tenancy.columns import org_column


class Chunk(Base):
    __tablename__ = "chunks"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String, primary_key=True)
    content_version_id: Mapped[str] = mapped_column(String, index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)  # heading | paragraph | image
    text: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String, index=True)
    data_class: Mapped[str] = mapped_column(String)
    # colour / font size / background etc., kept for the hidden-content checks.
    style: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ClaimUnit(Base):
    __tablename__ = "claim_units"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String, primary_key=True)
    review_id: Mapped[str] = mapped_column(String, index=True)
    content_version_id: Mapped[str] = mapped_column(String)
    normalized_claim: Mapped[str] = mapped_column(String)
    # [{chunk_id, start, end}] — a claim can span several chunks.
    span_refs: Mapped[list] = mapped_column(JSON, default=list)
    # [{fact_id, version}] the normalised claim depends on.
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Finding(Base):
    __tablename__ = "findings"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String, primary_key=True)
    review_id: Mapped[str] = mapped_column(String, index=True)
    content_version_id: Mapped[str] = mapped_column(String)
    unit_type: Mapped[str] = mapped_column(String)
    spans: Mapped[list] = mapped_column(JSON, default=list)
    check: Mapped[str] = mapped_column(String)
    tier: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fact_ids: Mapped[list] = mapped_column(JSON, default=list)
    cited_text: Mapped[str] = mapped_column(String)
    explanation: Mapped[str] = mapped_column(String)
    trace: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    models_used: Mapped[list] = mapped_column(JSON, default=list)
    vote: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fix_available: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="open")
    # The inputs Replay needs: versions, rule, facts and the as-of date.
    manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ReviewCache(Base):
    __tablename__ = "review_cache"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # hash(chunk text, channel, rule id@version, prompt ver, model ver, policy ver)
    cache_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    unit_type: Mapped[str] = mapped_column(String)
    verdict: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # the cached finding
    depends_on: Mapped[list] = mapped_column(JSON, default=list)  # fact id + version
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)  # input manifest
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
