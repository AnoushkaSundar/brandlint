"""Gateway table models (Alapan-owned).

`gateway_log` records every llm.call: provider, model, route, what was masked,
latency and outcome. It feeds the disclosure panel and the audit log.
`token_vault` maps numbered tokens back to the values they replaced.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.tenancy.columns import org_column


class GatewayLog(Base):
    __tablename__ = "gateway_log"
    org_id: Mapped[str] = org_column()

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


class TokenVault(Base):
    __tablename__ = "token_vault"
    org_id: Mapped[str] = org_column()
    __table_args__ = (
        UniqueConstraint("scope", "token", name="uq_token_vault_scope_token"),
        UniqueConstraint("scope", "value", name="uq_token_vault_scope_value"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # The review id, so a value keeps one token throughout a review.
    scope: Mapped[str] = mapped_column(String, nullable=False, index=True)
    token: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    entity: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
