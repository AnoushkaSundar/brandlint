"""ci_runs and ci_run_files, and content.external_ref, for the CI/CD integration

A run is one submission of copy files from CI, and each file points at the content, version
and review it went through. `content.external_ref` ("<repo>:<path>") lets the same file
across pull requests be one piece with versions. Both new tables are tenant tables: on
Postgres they get Row-Level Security.

Take a database backup before running this against real data. The downgrade drops both
tables and the column, and every CI run recorded in them.

Revision ID: anoushka_0010
Revises: anoushka_0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anoushka_0010"
down_revision: str | None = "anoushka_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Read by tests/test_rls.py, so the tables locked here stay equal to the inventory.
RLS_TABLES = ["ci_runs", "ci_run_files"]

POLICY = "tenant_isolation"
ORG = "org_id = nullif(current_setting('app.org_id', true), '')::uuid"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column("content", sa.Column("external_ref", sa.String(512), nullable=True))
    op.create_index("ix_content_external_ref", "content", ["external_ref"])

    op.create_table(
        "ci_runs",
        sa.Column("org_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("repo", sa.String(255), nullable=False),
        sa.Column("pr", sa.Integer(), nullable=True),
        sa.Column("sha", sa.String(64), nullable=False),
        sa.Column("base_sha", sa.String(64), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("result", sa.String(8), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("token_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["token_id"], ["service_tokens.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "run_key"),
    )
    op.create_index("ix_ci_runs_org_id", "ci_runs", ["org_id"])

    op.create_table(
        "ci_run_files",
        sa.Column("org_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.String(36), nullable=False),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("review_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["ci_runs.id"]),
        sa.ForeignKeyConstraint(["content_id"], ["content.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["content_versions.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ci_run_files_org_id", "ci_run_files", ["org_id"])
    op.create_index("ix_ci_run_files_run_id", "ci_run_files", ["run_id"])
    op.create_index("ix_ci_run_files_content_id", "ci_run_files", ["content_id"])

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
    op.drop_index("ix_ci_run_files_content_id", table_name="ci_run_files")
    op.drop_index("ix_ci_run_files_run_id", table_name="ci_run_files")
    op.drop_index("ix_ci_run_files_org_id", table_name="ci_run_files")
    op.drop_table("ci_run_files")
    op.drop_index("ix_ci_runs_org_id", table_name="ci_runs")
    op.drop_table("ci_runs")
    op.drop_index("ix_content_external_ref", table_name="content")
    with op.batch_alter_table("content") as batch:
        batch.drop_column("external_ref")
