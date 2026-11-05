"""Brand-memory graph edges (Alapan-owned), stored as a Postgres edge table.

Edge types: CITES, SUPPORTED_BY, CONTAINS, MENTIONS, RENAMED_TO, HAS, VIOLATES,
RESOLVED_BY, SUPERSEDES, MADE_BY, AUTHORED_BY. Written at ingest and decision
time, never during a review. Node ids are plain strings (no cross-owner FKs).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, index=True)
    src_type: Mapped[str] = mapped_column(String)
    src_id: Mapped[str] = mapped_column(String, index=True)
    dst_type: Mapped[str] = mapped_column(String)
    dst_id: Mapped[str] = mapped_column(String, index=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
