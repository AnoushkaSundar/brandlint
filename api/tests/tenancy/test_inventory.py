"""Every table is accounted for, and each tenant table gets its org_id in its own block.

The classification tests pass today and keep passing: adding a table without deciding
whether it belongs to an org fails them. The org_id tests are expected to fail until
the block that adds the column, and strict xfail turns them into failures the moment
they start passing, which is the reminder to remove the marker.
"""

from __future__ import annotations

import pytest
from app.db import Base

from tests.tenancy import inventory
from tests.tenancy.inventory import LANDED_BLOCKS, SHARED_TABLES, TENANT_TABLES


def until_block(block: int) -> list:
    """An expected failure until the block lands, and an ordinary test after."""
    if block in LANDED_BLOCKS:
        return []
    return [
        pytest.mark.xfail(
            strict=True,
            reason=f"Block {block} adds this. It passes once the block is in LANDED_BLOCKS.",
        )
    ]


def test_every_table_is_classified():
    missing = inventory.unclassified(inventory.model_tables())
    assert not missing, (
        f"These tables are in neither TENANT_TABLES nor SHARED_TABLES: {sorted(missing)}. "
        "Decide whether each belongs to one organisation, and add it."
    )


def test_a_table_nobody_listed_is_caught():
    assert inventory.unclassified({"users", "brand_new_table"}) == {"brand_new_table"}


def test_the_allow_list_has_no_stale_entries():
    gone = inventory.stale(inventory.model_tables())
    assert not gone, f"No model defines these tables any more: {sorted(gone)}"


def test_only_organizations_is_shared():
    assert SHARED_TABLES == {"organizations"}
    assert not SHARED_TABLES & set(TENANT_TABLES)


def test_the_organizations_table_exists():
    assert "organizations" in inventory.model_tables()


@pytest.mark.parametrize(
    "table",
    [
        pytest.param(name, id=name, marks=until_block(block))
        for name, block in TENANT_TABLES.items()
    ],
)
def test_a_tenant_table_has_a_required_org_id(table):
    inventory.model_tables()
    columns = Base.metadata.tables[table].columns
    assert "org_id" in columns, f"{table} has no org_id column"
    assert not columns["org_id"].nullable, f"{table}.org_id allows NULL"
