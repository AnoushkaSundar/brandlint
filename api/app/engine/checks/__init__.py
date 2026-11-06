"""Tier-0 code checks. Each returns `Finding`s (tier=0, deterministic) that cite
a brand rule, an approved fact, or a built-in platform security rule."""

from __future__ import annotations

from app.engine.checks.context import (
    SEC_HIDDEN_CONTENT,
    SEC_INJECTION,
    CheckContext,
)
from app.engine.checks.facts import check_confidential_terms, check_fact_expiry
from app.engine.checks.hidden import check_hidden_content
from app.engine.checks.injection import detect_instructions
from app.engine.checks.required import check_required_elements
from app.engine.checks.routing import checks_for, run_tier0
from app.engine.checks.terms import check_terms

__all__ = [
    "SEC_HIDDEN_CONTENT",
    "SEC_INJECTION",
    "CheckContext",
    "check_confidential_terms",
    "check_fact_expiry",
    "check_hidden_content",
    "check_required_elements",
    "check_terms",
    "checks_for",
    "detect_instructions",
    "run_tier0",
]
