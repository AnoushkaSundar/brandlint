"""Ingest: code decides whether a rule is checked by code, not the model.

A real run marked six judgment rules `deterministic`. Nothing checks those but the
AI, and the AI only judges `judgment` rules, so they were silently never checked.
"""

from __future__ import annotations

import pytest
from app.admin.ingest import DraftIn, checked_type
from app.contracts import RuleType


def draft(text, kind="deterministic"):
    return DraftIn(type=kind, text=text, clause_ref="§1.1", severity="high")


TERM_RULES = {"R-TERM-01", "R-TERM-02", "R-TERM-03"}


@pytest.mark.parametrize(
    ("rule_id", "text"),
    [
        ("R-CLAIM-01", "Every statistic must come from the approved fact sheet."),
        ("R-CLAIM-03", "Do not promise outcomes. Avoid guarantees."),
        ("R-CLAIM-04", "Do not compare Tarnhollow with a named competitor."),
        ("R-TONE-01", "Write in plain English with short sentences."),
        ("R-TONE-04", "Use contractions so the voice stays conversational."),
        ("R-VIS-03", "Images should feel warm and human."),
    ],
)
def test_a_rule_no_code_checks_is_judged_by_the_ai(rule_id, text):
    assert checked_type(draft(text), rule_id, TERM_RULES) == RuleType.judgment


@pytest.mark.parametrize(
    ("rule_id", "text"),
    [
        ("R-TERM-01", "Never use unprovable superlatives."),
        ("R-CLAIM-02", "Never publish a statistic after its valid-until date."),
        ("R-CLAIM-05", "Never mention unreleased products or internal codenames."),
        ("R-INT-01", "Published content must not contain hidden text."),
        ("R-VIS-01", "Use the logo at its original proportions."),
        ("R-VIS-02", "Use only the six palette colours."),
    ],
)
def test_a_rule_a_code_check_covers_stays_deterministic(rule_id, text):
    assert checked_type(draft(text, "judgment"), rule_id, TERM_RULES) == (
        RuleType.deterministic
    )


def test_a_required_element_keeps_its_type():
    found = checked_type(draft("Posts carry the disclaimer.", "must_include"), "R-REQ-01", set())
    assert found == RuleType.must_include


def test_an_unnumbered_clause_is_still_typed():
    assert checked_type(draft("Be kind."), None, TERM_RULES) == RuleType.judgment
