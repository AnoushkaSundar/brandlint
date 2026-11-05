from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.defaults import new_id, utc_now
from app.db import Base


class Rule(Base):
    __tablename__ = "rules"

    # A change adds a new version and never edits an old one.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    clause_ref: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    channel_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    supersedes: Mapped[str | None] = mapped_column(String(64))


class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(String(255))
    source_doc: Mapped[str] = mapped_column(String(255))
    owner: Mapped[str] = mapped_column(String(255))
    valid_until: Mapped[date | None] = mapped_column(Date)
    data_class: Mapped[str] = mapped_column(String(32))


class Term(Base):
    __tablename__ = "terms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    preferred: Mapped[str] = mapped_column(String(255))
    banned: Mapped[list[str]] = mapped_column(JSON, default=list)
    renamed_from: Mapped[str | None] = mapped_column(String(255))


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    file_ref: Mapped[str] = mapped_column(String(512))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    file_ref: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Gap(Base):
    __tablename__ = "gaps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_id: Mapped[str] = mapped_column(String(64), index=True)
    check: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
