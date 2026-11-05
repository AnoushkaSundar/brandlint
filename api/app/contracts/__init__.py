"""BrandLint shared contracts (v1).

Implemented from docs/contracts.md and mirrored in web/lib/contracts.ts
(Anoushka owns the TypeScript side). Frozen after block 2 — any change goes
through its own contracts/vN PR that both owners approve.
"""

from __future__ import annotations

from .enums import (
    AssetKind,
    CheckType,
    ContentState,
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
from .models import (
    Asset,
    Decision,
    Fact,
    Finding,
    FixSuggestion,
    Gap,
    Precedent,
    Proposal,
    ProposalEval,
    ProposalEvidence,
    Rule,
    Span,
    Term,
    Trace,
    TraceStep,
    Vote,
)

__all__ = [
    "Asset",
    "AssetKind",
    "CheckType",
    "ContentState",
    "DataClass",
    "Decision",
    "DecisionAction",
    "Fact",
    "Finding",
    "FindingStatus",
    "FixSuggestion",
    "Gap",
    "Precedent",
    "Proposal",
    "ProposalEval",
    "ProposalEvidence",
    "ProposalKind",
    "ProposalStatus",
    # enums
    "Role",
    "Rule",
    "RuleStatus",
    "RuleType",
    "Severity",
    # models
    "Span",
    "Term",
    "Trace",
    "TraceStep",
    "UnitType",
    "Verdict",
    "Vote",
]
