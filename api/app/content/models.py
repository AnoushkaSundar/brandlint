from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.defaults import new_id, utc_now
from app.db import Base
from app.tenancy.columns import org_column


class Content(Base):
    __tablename__ = "content"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(32))
    # "in-house", an agency name or an AI tool name.
    source: Mapped[str] = mapped_column(String(255))
    data_class: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), default="draft")
    # Where the copy lives outside BrandLint: for a CI run, "<repo>:<path>", so the same file
    # across pull requests is one piece with versions.
    external_ref: Mapped[str | None] = mapped_column(String(512), index=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ContentVersion(Base):
    __tablename__ = "content_versions"
    org_id: Mapped[str] = org_column()
    __table_args__ = (UniqueConstraint("content_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_id: Mapped[str] = mapped_column(ForeignKey("content.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    file_ref: Mapped[str | None] = mapped_column(String(512))
    file_name: Mapped[str | None] = mapped_column(String(255))
    # The text has accepted fixes in it, which an uploaded file can't show.
    fixes_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
