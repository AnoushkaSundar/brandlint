"""alapan: engine, memory and governance tables

Revision ID: alapan_0002_engine_tables
Revises: alapan_0001_gateway_log
Create Date: 2026-11-05

Chained onto alapan_0001 (gateway_log), which merged first, so main keeps a
single Alembic head.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "alapan_0002_engine_tables"
down_revision: str | None = "alapan_0001_gateway_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("content_version_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("data_class", sa.String(), nullable=False),
        sa.Column("style", sa.JSON(), nullable=True),
    )
    op.create_index("ix_chunks_content_version_id", "chunks", ["content_version_id"])
    op.create_index("ix_chunks_content_hash", "chunks", ["content_hash"])

    op.create_table(
        "claim_units",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("review_id", sa.String(), nullable=False),
        sa.Column("content_version_id", sa.String(), nullable=False),
        sa.Column("normalized_claim", sa.String(), nullable=False),
        sa.Column("span_refs", sa.JSON(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_claim_units_review_id", "claim_units", ["review_id"])

    op.create_table(
        "findings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("review_id", sa.String(), nullable=False),
        sa.Column("content_version_id", sa.String(), nullable=False),
        sa.Column("unit_type", sa.String(), nullable=False),
        sa.Column("spans", sa.JSON(), nullable=False),
        sa.Column("check", sa.String(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rule_id", sa.String(), nullable=True),
        sa.Column("rule_version", sa.Integer(), nullable=True),
        sa.Column("fact_ids", sa.JSON(), nullable=False),
        sa.Column("cited_text", sa.String(), nullable=False),
        sa.Column("explanation", sa.String(), nullable=False),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("ai_generated", sa.Boolean(), nullable=False),
        sa.Column("models_used", sa.JSON(), nullable=False),
        sa.Column("vote", sa.JSON(), nullable=True),
        sa.Column("fix_available", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_findings_review_id", "findings", ["review_id"])

    op.create_table(
        "review_cache",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("cache_key", sa.String(), nullable=False),
        sa.Column("unit_type", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_review_cache_cache_key", "review_cache", ["cache_key"], unique=True
    )

    op.create_table(
        "edges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("src_type", sa.String(), nullable=False),
        sa.Column("src_id", sa.String(), nullable=False),
        sa.Column("dst_type", sa.String(), nullable=False),
        sa.Column("dst_id", sa.String(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_edges_type", "edges", ["type"])
    op.create_index("ix_edges_src_id", "edges", ["src_id"])
    op.create_index("ix_edges_dst_id", "edges", ["dst_id"])

    op.create_table(
        "proposals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("rule_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("current", sa.String(), nullable=False),
        sa.Column("suggested", sa.String(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("eval", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_proposals_rule_id", "proposals", ["rule_id"])

    op.create_table(
        "spot_checks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("content_id", sa.String(), nullable=False),
        sa.Column("review_id", sa.String(), nullable=False),
        sa.Column(
            "sampled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewer_id", sa.String(), nullable=True),
        sa.Column("result", sa.String(), nullable=True),
    )
    op.create_index("ix_spot_checks_content_id", "spot_checks", ["content_id"])

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("false_flag_rate", sa.Float(), nullable=True),
        sa.Column("attack_success_rate", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_index("ix_spot_checks_content_id", table_name="spot_checks")
    op.drop_table("spot_checks")
    op.drop_index("ix_proposals_rule_id", table_name="proposals")
    op.drop_table("proposals")
    op.drop_index("ix_edges_dst_id", table_name="edges")
    op.drop_index("ix_edges_src_id", table_name="edges")
    op.drop_index("ix_edges_type", table_name="edges")
    op.drop_table("edges")
    op.drop_index("ix_review_cache_cache_key", table_name="review_cache")
    op.drop_table("review_cache")
    op.drop_index("ix_findings_review_id", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_claim_units_review_id", table_name="claim_units")
    op.drop_table("claim_units")
    op.drop_index("ix_chunks_content_hash", table_name="chunks")
    op.drop_index("ix_chunks_content_version_id", table_name="chunks")
    op.drop_table("chunks")
