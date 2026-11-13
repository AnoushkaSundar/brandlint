"""ci_policies: what counts as a failure for a workspace's CI runs

One row per org, made when an admin first saves the policy. Until then the defaults apply:
a VIOLATION at medium or above fails, and so does an UNSURE finding. A tenant table: on
Postgres it gets Row-Level Security.

Take a database backup before running this against real data. The downgrade drops the table
and every saved policy, which puts every workspace back on the defaults.

Revision ID: anoushka_0011
Revises: anoushka_0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anoushka_0011"
down_revision: str | None = "anoushka_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = ["ci_policies"]

POLICY = "tenant_isolation"
ORG = "org_id = nullif(current_setting('app.org_id', true), '')::uuid"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "ci_policies",
        sa.Column("org_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("severity_threshold", sa.String(16), nullable=False),
        sa.Column("fail_on_unsure", sa.Boolean(), nullable=False),
        sa.Column("ignore_rules", sa.JSON(), nullable=False),
        sa.Column("max_waiting_minutes", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id"),
    )
    op.create_index("ix_ci_policies_org_id", "ci_policies", ["org_id"])
    if _is_postgres():
        for table in RLS_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
            op.execute(f"CREATE POLICY {POLICY} ON {table} USING ({ORG}) WITH CHECK ({ORG})")


def downgrade() -> None:
    if _is_postgres():
        for table in RLS_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    op.drop_index("ix_ci_policies_org_id", table_name="ci_policies")
    op.drop_table("ci_policies")
