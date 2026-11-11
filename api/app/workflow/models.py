from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.defaults import new_id, utc_now
from app.db import Base
from app.tenancy.columns import org_column


class Review(Base):
    __tablename__ = "reviews"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_version_id: Mapped[str] = mapped_column(
        ForeignKey("content_versions.id"), index=True
    )
    # The engine's id for this review, which the findings stream is read by.
    engine_review_id: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(32))
    # Pinned when the review starts, so later rule changes can't alter it.
    rulebook_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ReviewStateLog(Base):
    __tablename__ = "review_state_log"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_id: Mapped[str] = mapped_column(ForeignKey("content.id"), index=True)
    from_state: Mapped[str] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Decision(Base):
    __tablename__ = "decisions"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Finding ids repeat between mock reviews, so decisions are scoped to a review.
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"), index=True)
    # Findings belong to the engine, so this is a plain id rather than a foreign key.
    finding_id: Mapped[str] = mapped_column(String(255), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    # Where this left the finding. The same action can end differently.
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    fix_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )


class FixOffer(Base):
    """What the engine suggested. Accepting a fix uses this, never the request."""

    __tablename__ = "fix_offers"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"), index=True)
    finding_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    original: Mapped[str] = mapped_column(Text)
    suggested: Mapped[str] = mapped_column(Text)
    diff: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Comment(Base):
    __tablename__ = "comments"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_version_id: Mapped[str] = mapped_column(
        ForeignKey("content_versions.id"), index=True
    )
    # Empty for a comment on the whole version.
    finding_id: Mapped[str | None] = mapped_column(String(255), index=True)
    span: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("comments.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    org_id: Mapped[str] = org_column()

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(255), index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    rulebook_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
