"""Which tables belong to one organisation, and which are shared by all of them.

Every table is in exactly one of the two lists, so adding a table forces a decision.
The number says which block of docs/multitenancy.md gives the table its org_id; the
isolation tests for that table stop being expected failures in that block.
"""

from __future__ import annotations

import importlib
import pkgutil

# Block 1 adds org_id to users, Block 3 to the product tables, Block 4 to the rest.
TENANT_TABLES: dict[str, int] = {
    "users": 1,
    # Product (Anoushka).
    "content": 3,
    "content_versions": 3,
    "reviews": 3,
    "review_state_log": 3,
    "decisions": 3,
    "fix_offers": 3,
    "comments": 3,
    "audit_log": 3,
    "rules": 3,
    "facts": 3,
    "terms": 3,
    "assets": 3,
    "ingest_jobs": 3,
    "gaps": 3,
    # The CI/CD integration (docs/ci-integration.md): its tables carry org_id from the start.
    "service_tokens": 3,
    "ci_runs": 3,
    "ci_run_files": 3,
    # Engine (Alapan).
    "chunks": 4,
    "claim_units": 4,
    "findings": 4,
    "review_cache": 4,
    # Memory, gateway and governance (Alapan).
    "edges": 4,
    "gateway_log": 4,
    "token_vault": 4,
    "proposals": 4,
    "spot_checks": 4,
    "eval_runs": 4,
}

# Blocks that have landed. Their tests must pass, so they carry no expected-failure marker.
# Add a block here when it merges.
LANDED_BLOCKS = frozenset({0, 1, 3, 4})

# The organisations themselves can't carry an org_id.
SHARED_TABLES = frozenset({"organizations"})


def model_tables() -> set[str]:
    """Every table the app's models define."""
    import app

    for module in pkgutil.walk_packages(app.__path__, prefix="app."):
        if module.name.endswith(".models"):
            importlib.import_module(module.name)
    from app.db import Base

    return {table.name for table in Base.metadata.sorted_tables}


def unclassified(tables: set[str]) -> set[str]:
    """Tables that are neither tenant-owned nor shared."""
    return tables - set(TENANT_TABLES) - SHARED_TABLES


def stale(tables: set[str]) -> set[str]:
    """Tenant tables that no model defines any more. Shared ones arrive in Block 1."""
    return set(TENANT_TABLES) - tables
