"""Gateway table models (Alapan-owned).

`gateway_log` records every llm.call: provider, model, route, what was masked,
latency and outcome. It feeds the disclosure panel and the audit log.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GatewayLog(Base):
    __tablename__ = "gateway_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    data_class: Mapped[str] = mapped_column(String, nullable=False)
    rule_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    route: Mapped[str] = mapped_column(String, nullable=False)
    # entity -> count of what was masked; populated by the masking layer (block 4).
    masked: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    review_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # ok | error | blocked
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
