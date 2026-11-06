"""gap ids hold the engine's stable ids

The critic builds them from the finding id, which is longer than a UUID.

Revision ID: anoushka_0004
Revises: anoushka_0003
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anoushka_0004"
down_revision: str | None = "anoushka_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("gaps") as batch:
        batch.alter_column(
            "id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=255),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("gaps") as batch:
        batch.alter_column(
            "id",
            existing_type=sa.String(length=255),
            type_=sa.String(length=36),
            existing_nullable=False,
        )
