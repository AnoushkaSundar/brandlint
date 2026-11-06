"""decisions belong to a review and keep the fix text; finding ids can be long

Real finding ids are `{review}:{check}:{hash}`, which is longer than 64 characters.

Revision ID: anoushka_0005
Revises: anoushka_0004
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anoushka_0005"
down_revision: str | None = "anoushka_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _resize(table: str, column: str, old: int, new: int) -> None:
    with op.batch_alter_table(table) as batch:
        batch.alter_column(
            column,
            existing_type=sa.String(length=old),
            type_=sa.String(length=new),
        )


def upgrade() -> None:
    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("review_id", sa.String(length=36), nullable=False))
        batch.add_column(sa.Column("fix_text", sa.Text(), nullable=True))
        batch.create_index(batch.f("ix_decisions_review_id"), ["review_id"])
        batch.create_foreign_key(
            "fk_decisions_review_id_reviews", "reviews", ["review_id"], ["id"]
        )
    _resize("decisions", "finding_id", 64, 255)
    _resize("comments", "finding_id", 64, 255)
    _resize("audit_log", "target_id", 64, 255)


def downgrade() -> None:
    _resize("audit_log", "target_id", 255, 64)
    _resize("comments", "finding_id", 255, 64)
    _resize("decisions", "finding_id", 255, 64)
    with op.batch_alter_table("decisions") as batch:
        batch.drop_constraint("fk_decisions_review_id_reviews", type_="foreignkey")
        batch.drop_index(batch.f("ix_decisions_review_id"))
        batch.drop_column("fix_text")
        batch.drop_column("review_id")
