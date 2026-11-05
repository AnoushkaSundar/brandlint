"""alapan: gateway_log table

Revision ID: alapan_0001_gateway_log
Revises:
Create Date: 2026-11-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "alapan_0001_gateway_log"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gateway_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("data_class", sa.String(), nullable=False),
        sa.Column("rule_ids", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("masked", sa.JSON(), nullable=True),
        sa.Column("review_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_gateway_log_review_id", "gateway_log", ["review_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_gateway_log_review_id", table_name="gateway_log")
    op.drop_table("gateway_log")
