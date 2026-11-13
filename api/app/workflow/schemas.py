from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.content.schemas import ContentOut
from app.contracts import (
    CheckType,
    ContentState,
    DecisionAction,
    FindingStatus,
    Severity,
    Span,
)


class DecisionIn(BaseModel):
    action: DecisionAction
    # Bounded, so one request can't put a megabyte into the audit log.
    reason: str | None = Field(default=None, max_length=2000)
    # The creator's wording, for edit_fix. accept_fix uses the engine's offer.
    fix_text: str | None = Field(default=None, max_length=10_000)
    # For accept_fix: which offer was on screen, so nothing unseen gets saved.
    attempt: int | None = None


class FixRequest(BaseModel):
    # False returns the stored suggestion, so reopening spends no attempt.
    again: bool = False


class TransitionIn(BaseModel):
    to: ContentState
    reason: str | None = Field(default=None, max_length=2000)


class FindingStanding(BaseModel):
    id: str
    status: FindingStatus
    fix_text: str | None
    # The same list the server enforces, so the UI can't offer what would be refused.
    allowed: list[DecisionAction]


class MoveOut(BaseModel):
    to: ContentState
    needs_reason: bool
    blocked_by: str | None


class Board(BaseModel):
    state: ContentState
    legal_required: bool
    can_restart: bool
    # A reviewer let hidden text through, so manager and legal see a notice.
    hidden_overridden: bool
    findings: list[FindingStanding]
    moves: list[MoveOut]


class QueueItem(BaseModel):
    content_id: str
    title: str
    channel: str
    state: ContentState
    finding_id: str
    kind: Literal["unsure", "override", "fix", "needs_override"]
    severity: Severity
    check: CheckType
    explanation: str
    # No source, no flag: a reviewer decides with the citation in front of them.
    rule_id: str | None
    fact_ids: list[str]
    cited_text: str
    # The creator's reason, for an override.
    reason: str | None
    # The wording to sign off, for a fix.
    fix_text: str | None


class Queue(BaseModel):
    items: list[QueueItem]
    # Pieces submitted and waiting for a reviewer to pass or send back.
    ready: list[ContentOut]
    # Titles of pieces whose findings couldn't be read just now.
    unavailable: list[str]


class CommentIn(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    content_version_id: str
    finding_id: str | None = None
    span: Span | None = None
    parent_id: str | None = None


class CommentOut(BaseModel):
    id: str
    content_version_id: str
    finding_id: str | None
    span: dict[str, Any] | None
    parent_id: str | None
    author: str
    body: str
    mentions: list[str]
    created_at: datetime


class StateEntry(BaseModel):
    from_state: ContentState
    to_state: ContentState
    actor: str
    reason: str | None
    created_at: datetime


class DecisionEntry(BaseModel):
    finding_id: str
    action: DecisionAction
    actor: str
    role: str
    reason: str | None
    version: int
    created_at: datetime


class PublishedStamp(BaseModel):
    version: int
    rulebook_version: int
    approvers: list[str]
    published_at: datetime


class History(BaseModel):
    states: list[StateEntry]
    decisions: list[DecisionEntry]
    stamp: PublishedStamp | None


class AuditEntry(BaseModel):
    id: str
    actor: str
    role: str
    action: str
    target_type: str
    target_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    rulebook_version: int | None
    created_at: datetime


class AuditPage(BaseModel):
    total: int
    items: list[AuditEntry]
