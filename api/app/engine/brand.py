"""Brand data for a review: the pinned rulebook, facts and terms.

Reads the demo brand until the product's admin functions exist, then this one
function changes. Only approved rules ever reach a review.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.contracts import Fact, Rule, RuleStatus, Term


@dataclass
class BrandData:
    rules: list[Rule]
    facts: list[Fact]
    terms: list[Term]


def _demo_dir() -> Path:
    configured = os.getenv("DEMO_DIR")
    return Path(configured) if configured else Path(__file__).parents[3] / "demo"


def _load(name: str) -> list[dict]:
    return json.loads((_demo_dir() / "brand" / name).read_text("utf8"))


def load_brand(rulebook_version: int) -> BrandData:
    rules = [Rule(**row) for row in _load("rules.json")]
    return BrandData(
        rules=[
            rule
            for rule in rules
            if rule.status == RuleStatus.approved and rule.version <= rulebook_version
        ],
        facts=[Fact(**row) for row in _load("facts.json")],
        terms=[Term(**row) for row in _load("terms.json")],
    )
