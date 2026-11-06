"""contracts v2 fields on rules and terms

Revision ID: anoushka_0003
Revises: anoushka_0002
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anoushka_0003"
down_revision: str | None = "anoushka_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("rules") as batch:
        batch.add_column(sa.Column("required_text", sa.Text(), nullable=True))
    with op.batch_alter_table("terms") as batch:
        batch.add_column(sa.Column("rule_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("rule_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("terms") as batch:
        batch.drop_column("rule_version")
        batch.drop_column("rule_id")
    with op.batch_alter_table("rules") as batch:
        batch.drop_column("required_text")
