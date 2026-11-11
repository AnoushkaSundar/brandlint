from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.defaults import new_id, utc_now
from app.db import Base


class Organization(Base):
    """One workspace. Everything a user creates belongs to the org they are in."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("kind IN ('demo', 'sandbox')", name="ck_organizations_kind"),
        CheckConstraint(
            "status IN ('active', 'suspended')", name="ck_organizations_status"
        ),
    )

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=new_id
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # "demo" is Tarnhollow. "sandbox" is a workspace a visitor created.
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    # A sandbox stops working at this time. None never expires.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    # "agency" or "in-house", for creators.
    tag: Mapped[str | None] = mapped_column(String(32))
    # The source of truth for which workspace a request belongs to. Never read an org
    # from a token, a body, a path, a query or a header.
    org_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("organizations.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
