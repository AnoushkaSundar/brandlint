"""alapan: token_vault table

Revision ID: alapan_0003_token_vault
Revises: anoushka_0001
Create Date: 2026-11-06

Whoever merges second re-chains down_revision so main keeps one Alembic head.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "alapan_0003_token_vault"
down_revision: str | None = "anoushka_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "token_vault",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("entity", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("scope", "token", name="uq_token_vault_scope_token"),
        sa.UniqueConstraint("scope", "value", name="uq_token_vault_scope_value"),
    )
    op.create_index("ix_token_vault_scope", "token_vault", ["scope"])


def downgrade() -> None:
    op.drop_index("ix_token_vault_scope", table_name="token_vault")
    op.drop_table("token_vault")
