"""Brand data for a review, read through the product's admin functions.

`rulebook_at` raises if the pinned rulebook has no approved rules, so a review
can never run against an empty rulebook and look clean.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.admin.brand import list_facts, list_terms
from app.admin.rulebook import rulebook_at
from app.contracts import Fact, Rule, Term


@dataclass
class BrandData:
    rules: list[Rule]
    facts: list[Fact]
    terms: list[Term]


def load_brand(session: Session, rulebook_version: int) -> BrandData:
    return BrandData(
        rules=rulebook_at(session, rulebook_version),
        facts=list_facts(session),
        terms=list_terms(session),
    )
