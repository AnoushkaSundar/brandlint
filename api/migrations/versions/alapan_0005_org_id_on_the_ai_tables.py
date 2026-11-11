"""org_id on the engine, memory, gateway and governance tables

For each of the 10 tables, in this order: add org_id nullable, put every existing row in
the Tarnhollow demo org, then make it required. Edges are keyed per org, because two orgs
can each hold a fact with the same id and so the same edge: their primary key becomes
(org_id, id).

The verdict cache key now includes the org, so entries written before this are never hit
again and the demo org's cache warms up again from scratch. That only costs model calls.

Take a database backup before running this against real data. Downgrading puts the old
edge key back, which fails if two orgs now hold the same edge, so remove the other orgs'
rows first.

Revision ID: alapan_0005
Revises: anoushka_0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "alapan_0005"
down_revision: str | None = "anoushka_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Repeated from app/auth/orgs.py on purpose. See anoushka_0006.
DEMO_ORG_ID = "00000000-0000-4000-8000-000000000001"

ORG = sa.Uuid(as_uuid=False)
PLAIN = [
    "chunks",
    "claim_units",
    "findings",
    "review_cache",
    "gateway_log",
    "token_vault",
    "proposals",
    "spot_checks",
    "eval_runs",
]
KEYED = {"edges": ["id"]}


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _set_key(table: str, old_name: str, new_name: str, columns: list[str]) -> None:
    if _is_postgres():
        op.drop_constraint(old_name, table, type_="primary")
        op.create_primary_key(new_name, table, columns)
    else:
        # SQLite rebuilds the table, and a named key replaces the unnamed one.
        with op.batch_alter_table(table) as batch:
            batch.create_primary_key(new_name, columns)


def upgrade() -> None:
    for table in [*PLAIN, *KEYED]:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("org_id", ORG, nullable=True))

        reference = sa.table(table, sa.column("org_id", ORG))
        op.execute(reference.update().values(org_id=DEMO_ORG_ID))

    for table in PLAIN:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("org_id", existing_type=ORG, nullable=False)
            batch.create_index(batch.f(f"ix_{table}_org_id"), ["org_id"])
            batch.create_foreign_key(
                f"fk_{table}_org_id_organizations", "organizations", ["org_id"], ["id"]
            )

    for table, key in KEYED.items():
        with op.batch_alter_table(table) as batch:
            batch.alter_column("org_id", existing_type=ORG, nullable=False)
            batch.create_foreign_key(
                f"fk_{table}_org_id_organizations", "organizations", ["org_id"], ["id"]
            )
        _set_key(table, f"{table}_pkey", f"pk_{table}", ["org_id", *key])


def downgrade() -> None:
    for table, key in KEYED.items():
        _set_key(table, f"pk_{table}", f"{table}_pkey", key)
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(
                f"fk_{table}_org_id_organizations", type_="foreignkey"
            )
            batch.drop_column("org_id")

    for table in PLAIN:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(
                f"fk_{table}_org_id_organizations", type_="foreignkey"
            )
            batch.drop_index(batch.f(f"ix_{table}_org_id"))
            batch.drop_column("org_id")
