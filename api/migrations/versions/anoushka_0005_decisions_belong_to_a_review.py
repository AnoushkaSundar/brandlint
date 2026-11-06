"""decisions belong to a review; fix offers are stored; finding ids can be long

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
        batch.add_column(sa.Column("status", sa.String(length=32), nullable=False))
        batch.add_column(sa.Column("fix_text", sa.Text(), nullable=True))
        batch.create_index(batch.f("ix_decisions_review_id"), ["review_id"])
        batch.create_foreign_key(
            "fk_decisions_review_id_reviews", "reviews", ["review_id"], ["id"]
        )
    _resize("decisions", "finding_id", 64, 255)
    _resize("comments", "finding_id", 64, 255)
    _resize("audit_log", "target_id", 64, 255)
    with op.batch_alter_table("content_versions") as batch:
        batch.add_column(
            sa.Column("fixes_applied", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_table(
        "fix_offers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("review_id", sa.String(length=36), sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("finding_id", sa.String(length=255), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("suggested", sa.Text(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_fix_offers_review_id"), "fix_offers", ["review_id"])
    op.create_index(op.f("ix_fix_offers_finding_id"), "fix_offers", ["finding_id"])


def downgrade() -> None:
    op.drop_table("fix_offers")
    with op.batch_alter_table("content_versions") as batch:
        batch.drop_column("fixes_applied")
    _resize("audit_log", "target_id", 255, 64)
    _resize("comments", "finding_id", 255, 64)
    _resize("decisions", "finding_id", 255, 64)
    with op.batch_alter_table("decisions") as batch:
        batch.drop_constraint("fk_decisions_review_id_reviews", type_="foreignkey")
        batch.drop_index(batch.f("ix_decisions_review_id"))
        batch.drop_column("fix_text")
        batch.drop_column("status")
        batch.drop_column("review_id")
