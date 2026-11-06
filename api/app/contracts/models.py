"""Shared Pydantic models, mirrored from docs/contracts.md.

Frozen after block 2. These are the wire/contract shapes exchanged between
Alapan's services and Anoushka's product. SQLAlchemy table models live
elsewhere (per owner) and are not these classes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .enums import (
    AssetKind,
    CheckType,
    DataClass,
    DecisionAction,
    FindingStatus,
    ProposalKind,
    ProposalStatus,
    Role,
    RuleStatus,
    RuleType,
    Severity,
    UnitType,
    Verdict,
)

# --- sub-objects ---


class Span(BaseModel):
    chunk_id: str
    start: int
    end: int


class TraceStep(BaseModel):
    tool: str
    input_summary: str
    output_summary: str


class Trace(BaseModel):
    steps: list[TraceStep] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    model: str | None = None


class Vote(BaseModel):
    variants: int
    agree: int
    split: bool


# --- core models ---


class Finding(BaseModel):
    id: str
    review_id: str
    content_version_id: str
    unit_type: UnitType
    spans: list[Span] = Field(default_factory=list)
    check: CheckType
    tier: Literal[0, 1, 2]
    verdict: Verdict
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    rule_id: str | None = None
    rule_version: int | None = None
    fact_ids: list[str] = Field(default_factory=list)
    cited_text: str
    explanation: str
    trace: Trace
    ai_generated: bool
    models_used: list[str] = Field(default_factory=list)
    vote: Vote | None = None
    fix_available: bool
    status: FindingStatus

    @model_validator(mode="after")
    def _require_a_source(self) -> Finding:
        # "No source, no flag": every finding shown to a user cites a rule
        # clause or an approved fact. Enforced here as a contract invariant.
        if not self.rule_id and not self.fact_ids:
            raise ValueError(
                "Finding must cite at least one of rule_id or fact_ids"
            )
        return self


class Rule(BaseModel):
    id: str
    version: int
    type: RuleType
    text: str
    clause_ref: str
    severity: Severity
    channel_scope: list[str] = Field(default_factory=list)
    status: RuleStatus
    supersedes: str | None = None
    # For must_include rules: the exact text that must appear in the content
    # (distinct from `text`, which describes the rule). The tier-0
    # required-element check looks for this, not the rule sentence.
    required_text: str | None = None


class Fact(BaseModel):
    id: str
    statement: str
    value: str
    source_doc: str
    owner: str
    valid_until: date | None = None
    data_class: DataClass
    version: int


class Term(BaseModel):
    id: str
    preferred: str
    banned: list[str] = Field(default_factory=list)
    renamed_from: str | None = None
    # The terminology rule this term is governed by. The tier-0 terms check
    # cites this rule (and uses its severity), so different terms can carry
    # different severities.
    rule_id: str | None = None
    rule_version: int | None = None


class Asset(BaseModel):
    id: str
    kind: AssetKind
    file_ref: str
    meta: dict = Field(default_factory=dict)


class Decision(BaseModel):
    id: str
    finding_id: str
    actor_id: str
    role: Role
    action: DecisionAction
    reason: str | None = None
    created_at: datetime


class Gap(BaseModel):
    id: str
    review_id: str
    check: CheckType
    text: str
    explanation: str
    created_at: datetime


class FixSuggestion(BaseModel):
    finding_id: str
    original: str
    suggested: str
    diff: str
    attempt: Literal[1, 2]


class Precedent(BaseModel):
    decision_id: str
    rule_id: str
    rule_version: int
    channel: str
    reason: str
    reviewer: str
    date: datetime


class ProposalEvidence(BaseModel):
    count: int
    examples: list[Span] = Field(default_factory=list)


class ProposalEval(BaseModel):
    passed: bool
    precision: float
    recall: float


class Proposal(BaseModel):
    id: str
    rule_id: str
    kind: ProposalKind
    current: str
    suggested: str
    evidence: ProposalEvidence
    eval: ProposalEval | None = None
    status: ProposalStatus


class Chunk(BaseModel):
    """A parsed content chunk, as served to the review screen."""

    id: str
    content_version_id: str
    ordinal: int
    kind: str  # heading | paragraph | image
    text: str
    content_hash: str
    data_class: DataClass
    style: dict | None = None


class ContentSource(BaseModel):
    """What the engine reviews, handed over in-process when a review starts.

    Never sent over HTTP. It carries bytes rather than a path or file reference
    so that no client can point the engine at a file on the server.
    """

    data_class: DataClass
    text: str = ""
    file_name: str | None = None
    file_bytes: bytes | None = None

    @model_validator(mode="after")
    def _require_content(self) -> ContentSource:
        if not self.text and not self.file_bytes:
            raise ValueError("ContentSource needs text or file_bytes")
        if self.file_bytes and not self.file_name:
            raise ValueError("file_bytes needs file_name, which gives the format")
        return self
