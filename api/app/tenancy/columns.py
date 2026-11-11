"""The org_id column every tenant table has."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import MappedColumn, mapped_column


def org_column(*, primary_key: bool = False) -> MappedColumn:
    """`org_id`, required, pointing at `organizations`.

    Tables keyed per org (rules, facts, terms, assets) pass `primary_key=True` and declare
    it first, so two orgs can hold the same id. The others get an index.
    """
    return mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("organizations.id"),
        primary_key=primary_key,
        index=not primary_key,
    )
