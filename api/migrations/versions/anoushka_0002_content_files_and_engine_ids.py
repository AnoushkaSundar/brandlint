"""content files and engine review ids

Revision ID: anoushka_0002
Revises: anoushka_0001
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anoushka_0002"
down_revision: str | None = "anoushka_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode lets SQLite add a required column, and is a plain ALTER on Postgres.
    with op.batch_alter_table("content_versions") as batch:
        batch.add_column(sa.Column("file_name", sa.String(length=255), nullable=True))
    with op.batch_alter_table("reviews") as batch:
        batch.add_column(
            sa.Column("engine_review_id", sa.String(length=64), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("reviews") as batch:
        batch.drop_column("engine_review_id")
    with op.batch_alter_table("content_versions") as batch:
        batch.drop_column("file_name")
