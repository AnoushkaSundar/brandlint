"""Tables for the CI/CD integration (docs/ci-integration.md)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.defaults import new_id, utc_now
from app.db import Base
from app.tenancy.columns import org_column


class ServiceToken(Base):
    """A machine's way in: a CI job calls the CI routes with it, and nothing else.

    The token itself is shown once, when it is made. Only its SHA-256 hash is kept, so a
    leaked database doesn't leak tokens. It belongs to one org, which is where every request
    made with it goes.
    """

    __tablename__ = "service_tokens"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # The first characters, so a person can tell tokens apart in a list.
    prefix: Mapped[str] = mapped_column(String(16))
    scopes: Mapped[list] = mapped_column(JSON, default=lambda: ["ci"])
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
