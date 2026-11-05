"""Shared enums, mirrored 1:1 from docs/contracts.md.

Frozen after block 2. Any change needs its own contracts/vN PR that both
owners approve. All enums are str-backed so they serialise as plain strings
and can be reused directly as SQLAlchemy column types.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    creator = "creator"
    reviewer = "reviewer"
    manager = "manager"
    legal = "legal"
    admin = "admin"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Verdict(str, Enum):
    VIOLATION = "VIOLATION"
    UNSURE = "UNSURE"
    PASS = "PASS"


class CheckType(str, Enum):
    tone = "tone"
    terminology = "terminology"
    messaging = "messaging"
    claim = "claim"
    visual = "visual"
    accessibility = "accessibility"
    hidden_content = "hidden_content"
    required_element = "required_element"
    tone_drift = "tone_drift"


class UnitType(str, Enum):
    chunk = "chunk"
    claim = "claim"
    document = "document"


class DataClass(str, Enum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"


class ContentState(str, Enum):
    draft = "draft"
    ai_review = "ai_review"
    resolving = "resolving"
    reviewer_check = "reviewer_check"
    manager_approval = "manager_approval"
    legal_signoff = "legal_signoff"
    published = "published"
    rejected = "rejected"


class FindingStatus(str, Enum):
    open = "open"
    fix_accepted = "fix_accepted"
    fix_edited = "fix_edited"
    override_pending = "override_pending"
    override_confirmed = "override_confirmed"
    override_rejected = "override_rejected"
    resolved = "resolved"


# --- inline enums used inside the models below ---


class RuleType(str, Enum):
    deterministic = "deterministic"
    judgment = "judgment"
    must_include = "must_include"


class RuleStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    retired = "retired"


class DecisionAction(str, Enum):
    accept_fix = "accept_fix"
    edit_fix = "edit_fix"
    override = "override"
    confirm_override = "confirm_override"
    reject_override = "reject_override"
    resolve = "resolve"


class AssetKind(str, Enum):
    logo = "logo"
    palette = "palette"
    image = "image"
    font = "font"


class ProposalKind(str, Enum):
    amendment = "amendment"
    anchor = "anchor"
    term = "term"
    severity = "severity"


class ProposalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
