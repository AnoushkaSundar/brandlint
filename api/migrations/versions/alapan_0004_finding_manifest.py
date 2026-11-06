"""alapan: findings keep the inputs Replay needs

Revision ID: alapan_0004_finding_manifest
Revises: alapan_0003_token_vault
Create Date: 2026-11-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "alapan_0004_finding_manifest"
down_revision: str | None = "alapan_0003_token_vault"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("findings") as batch:
        batch.add_column(sa.Column("manifest", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("findings") as batch:
        batch.drop_column("manifest")
