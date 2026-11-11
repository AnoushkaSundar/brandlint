"""What a request did to the database, to catch a write that crossed from one org to another.

A response can look harmless while the request changed or created rows that belong to
the other org, so the isolation test compares the database before and after.
"""

from __future__ import annotations

from app.db import Base
from sqlalchemy import Engine

# Rebuilt from other rows whenever someone reads the graph, so it isn't a write by the caller.
DERIVED_TABLES = frozenset({"edges"})

Snapshot = dict[tuple[str, tuple], str]


def snapshot(engine: Engine) -> Snapshot:
    """Every row of every table, by primary key."""
    rows: Snapshot = {}
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name in DERIVED_TABLES:
                continue
            keys = [column.name for column in table.primary_key.columns]
            for row in connection.execute(table.select()):
                values = row._mapping
                rows[(table.name, tuple(values[key] for key in keys))] = repr(
                    dict(values)
                )
    return rows


def problems(before: Snapshot, after: Snapshot, owned_ids: set[str]) -> list[str]:
    """Rows that refer to the org in `owned_ids` and were changed, deleted or newly created."""

    def refers(text: str) -> bool:
        return any(identifier in text for identifier in owned_ids)

    found = []
    for key, text in before.items():
        if not refers(text):
            continue
        if key not in after:
            found.append(f"deleted {key[0]} {key[1]}")
        elif after[key] != text:
            found.append(f"changed {key[0]} {key[1]}")
    for key, text in after.items():
        if key not in before and refers(text):
            found.append(f"created {key[0]} {key[1]}, which refers to the other org")
    return found
