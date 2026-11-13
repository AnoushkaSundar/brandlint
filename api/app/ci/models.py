"""Tables for the CI/CD integration (docs/ci-integration.md)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CIRun(Base):
    """One submission of copy files from CI: the files, and where the review of each stands.

    `run_key` identifies what was sent (repo, PR and every file's path and text hash), so
    sending the same thing again finds this run instead of making another.
    """

    __tablename__ = "ci_runs"
    __table_args__ = (UniqueConstraint("org_id", "run_key"),)
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_key: Mapped[str] = mapped_column(String(64))
    repo: Mapped[str] = mapped_column(String(255))
    pr: Mapped[int | None] = mapped_column(Integer)
    sha: Mapped[str] = mapped_column(String(64))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    # queued | running | done | error. A run is never "done" while a review is still going.
    state: Mapped[str] = mapped_column(String(16), default="running")
    # pass | fail, once the run is done. An error run has none.
    result: Mapped[str | None] = mapped_column(String(8))
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    token_id: Mapped[str | None] = mapped_column(ForeignKey("service_tokens.id"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CIRunFile(Base):
    __tablename__ = "ci_run_files"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("ci_runs.id"), index=True)
    path: Mapped[str] = mapped_column(String(512))
    # What the text hashed to, so unchanged text finds the review it already has.
    text_hash: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    content_id: Mapped[str] = mapped_column(ForeignKey("content.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("content_versions.id"))
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class CIPolicySetting(Base):
    """What counts as a failure for this workspace. One row per org, made when it is first saved;
    until then the defaults apply (see app.ci.verdict.DEFAULT_POLICY)."""

    __tablename__ = "ci_policies"
    __table_args__ = (UniqueConstraint("org_id"),)
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    severity_threshold: Mapped[str] = mapped_column(String(16), default="medium")
    fail_on_unsure: Mapped[bool] = mapped_column(Boolean, default=True)
    # Approved rule ids whose findings never fail a run.
    ignore_rules: Mapped[list] = mapped_column(JSON, default=list)
    max_waiting_minutes: Mapped[int] = mapped_column(Integer, default=15)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
