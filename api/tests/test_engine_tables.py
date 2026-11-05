"""Engine/memory/governance tables register on the shared Base and build cleanly."""

from __future__ import annotations

# Importing the model modules registers their tables on Base.metadata.
import app.engine.models
import app.governance.models
import app.memory.models  # noqa: F401
from app.db import Base
from sqlalchemy import create_engine, inspect

EXPECTED = {
    "chunks",
    "claim_units",
    "findings",
    "review_cache",
    "edges",
    "proposals",
    "spot_checks",
    "eval_runs",
}


def test_all_eight_tables_create_on_sqlite():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert EXPECTED <= tables


def test_findings_has_the_contract_columns():
    cols = {c.name for c in Base.metadata.tables["findings"].columns}
    assert {
        "unit_type",
        "spans",
        "check",
        "tier",
        "verdict",
        "severity",
        "confidence",
        "rule_id",
        "fact_ids",
        "cited_text",
        "trace",
        "ai_generated",
        "status",
    } <= cols
