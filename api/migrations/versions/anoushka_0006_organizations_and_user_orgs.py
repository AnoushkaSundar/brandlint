"""organisations, and every user belongs to one

In one migration and in this order, so there is never a user without an org:
1. create organizations,
2. add users.org_id, nullable,
3. create the Tarnhollow demo org and put every existing user in it,
4. make users.org_id required, indexed and a foreign key.

Take a database backup before running this against real data.

Revision ID: anoushka_0006
Revises: alapan_0004_finding_manifest
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "anoushka_0006"
down_revision: str | None = "alapan_0004_finding_manifest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Repeated from app/auth/orgs.py on purpose: a migration must not change when app code
# does. A test keeps the two equal.
DEMO_ORG_ID = "00000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.CheckConstraint("kind IN ('demo', 'sandbox')", name="ck_organizations_kind"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name="ck_organizations_status"
        ),
    )
    op.create_index(
        op.f("ix_organizations_slug"), "organizations", ["slug"], unique=True
    )

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("org_id", sa.Uuid(as_uuid=False), nullable=True))

    # Typed tables, so the id is stored the way the app reads it on every database.
    organizations = sa.table(
        "organizations",
        sa.column("id", sa.Uuid(as_uuid=False)),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("kind", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("status", sa.String),
    )
    users = sa.table("users", sa.column("org_id", sa.Uuid(as_uuid=False)))
    op.execute(
        organizations.insert().values(
            id=DEMO_ORG_ID,
            name="Tarnhollow",
            slug="tarnhollow",
            kind="demo",
            created_at=datetime.now(UTC),
            status="active",
        )
    )
    op.execute(users.update().values(org_id=DEMO_ORG_ID))

    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "org_id", existing_type=sa.Uuid(as_uuid=False), nullable=False
        )
        batch.create_index(batch.f("ix_users_org_id"), ["org_id"])
        batch.create_foreign_key(
            "fk_users_org_id_organizations", "organizations", ["org_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("fk_users_org_id_organizations", type_="foreignkey")
        batch.drop_index(batch.f("ix_users_org_id"))
        batch.drop_column("org_id")
    op.drop_index(op.f("ix_organizations_slug"), table_name="organizations")
    op.drop_table("organizations")
