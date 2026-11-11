"""org_id on the product tables

For each of the 14 product tables, in this order: add org_id nullable, put every
existing row in the Tarnhollow demo org, then make it required. Rules, facts, terms and
assets are keyed per org, so two orgs can each have "R1": their primary keys become
(org_id, id, version) for rules and facts and (org_id, id) for terms and assets.

Take a database backup before running this against real data. Downgrading puts the old
keys back, which fails if two orgs now hold the same id, so remove the other orgs' rows
first.

Revision ID: anoushka_0007
Revises: anoushka_0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anoushka_0007"
down_revision: str | None = "anoushka_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Repeated from app/auth/orgs.py on purpose. See anoushka_0006.
DEMO_ORG_ID = "00000000-0000-4000-8000-000000000001"

ORG = sa.Uuid(as_uuid=False)
# Tables that just gain an org_id and an index.
PLAIN = [
    "content",
    "content_versions",
    "reviews",
    "review_state_log",
    "decisions",
    "fix_offers",
    "comments",
    "audit_log",
    "ingest_jobs",
    "gaps",
]
# Tables keyed per org: the key they had, which org_id is put in front of.
KEYED = {
    "rules": ["id", "version"],
    "facts": ["id", "version"],
    "terms": ["id"],
    "assets": ["id"],
}


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
