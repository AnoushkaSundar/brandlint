"""service_tokens: a machine's way in for the CI/CD integration

A CI job authenticates with a token that belongs to one org. Only the token's SHA-256 hash
is stored. The table is a tenant table like the others: on Postgres it gets Row-Level
Security, with the same way through as users, because a token is looked up by its hash
before the org is known (app.tenancy.rls.auth_lookup).

Take a database backup before running this against real data. The downgrade drops the
table and every token in it.

Revision ID: anoushka_0009
Revises: anoushka_0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anoushka_0009"
down_revision: str | None = "anoushka_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Read by tests/test_rls.py, so the tables locked here stay equal to the inventory.
RLS_TABLES = ["service_tokens"]

POLICY = "tenant_isolation"
ORG = "org_id = nullif(current_setting('app.org_id', true), '')::uuid"
AUTH = "current_setting('app.auth', true) = 'on'"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "service_tokens",
        sa.Column("org_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_tokens_org_id", "service_tokens", ["org_id"])
    op.create_index(
        "ix_service_tokens_token_hash", "service_tokens", ["token_hash"], unique=True
    )

    if _is_postgres():
        for table in RLS_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
            op.execute(
                f"CREATE POLICY {POLICY} ON {table} USING ({ORG} OR {AUTH}) WITH CHECK ({ORG})"
            )


def downgrade() -> None:
    if _is_postgres():
        for table in RLS_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    op.drop_index("ix_service_tokens_token_hash", table_name="service_tokens")
    op.drop_index("ix_service_tokens_org_id", table_name="service_tokens")
    op.drop_table("service_tokens")
