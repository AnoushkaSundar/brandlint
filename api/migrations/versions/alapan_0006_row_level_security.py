"""row-level security: the database refuses another org's rows

A second lock behind the app-level scoping. On every tenant table this enables and
forces Row-Level Security with one policy: a row is visible, and can be written, only when
its org_id equals the app.org_id setting of the current transaction. With no setting, no
row matches, so a request that never named its org sees nothing and can write nothing.

It also creates the role the API should connect as, brandlint_app: not a superuser, not
able to bypass RLS, and owner of no table. Superusers and the table owner bypass RLS
unless it is forced, and superusers bypass it even then, so the API must not connect as
either. The role has no login until APP_DB_PASSWORD is set when this runs, or until you
give it one with ALTER ROLE.

The users table is the one tenant table left out. Signing in has to find a user by email
before any org is known, so an org-based policy there would lock everyone out. Users are
read through the scoped helpers everywhere else; see docs/rls.md for what closing that
gap needs.

Only Postgres has Row-Level Security, so on any other database this does nothing.

Revision ID: alapan_0006
Revises: alapan_0005
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "alapan_0006"
down_revision: str | None = "alapan_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Overridable so a test can use a role of its own. Roles belong to the whole server.
APP_ROLE = os.environ.get("APP_DB_ROLE", "brandlint_app")

# Every tenant table except users, written out so this migration never changes when the
# models do. A test keeps it equal to the inventory in tests/tenancy/inventory.py.
TENANT_TABLES = [
    # Product.
    "content",
    "content_versions",
    "reviews",
    "review_state_log",
    "decisions",
    "fix_offers",
    "comments",
    "audit_log",
    "rules",
    "facts",
    "terms",
    "assets",
    "ingest_jobs",
    "gaps",
    # Engine, memory, gateway and governance.
    "chunks",
    "claim_units",
    "findings",
    "review_cache",
    "edges",
    "gateway_log",
    "token_vault",
    "proposals",
    "spot_checks",
    "eval_runs",
]

POLICY = "tenant_isolation"
# An unset or empty setting becomes NULL, and NULL matches nothing.
ORG = "org_id = nullif(current_setting('app.org_id', true), '')::uuid"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
          END IF;
        END $$
        """
    )
    password = os.environ.get("APP_DB_PASSWORD")
    if password:
        # DDL can't take bound parameters, so the password goes through a setting and is
        # quoted by the server, never spliced into the statement here.
        op.get_bind().execute(
            sa.text("SELECT set_config('brandlint.app_password', :pw, true)"),
            {"pw": password},
        )
        op.execute(
            f"""
            DO $$ BEGIN
              EXECUTE format('ALTER ROLE {APP_ROLE} LOGIN PASSWORD %L',
                             current_setting('brandlint.app_password'));
            END $$
            """
        )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    # Migrations are not the app's business.
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    # Tables a later migration creates are reachable too, and are not forgotten.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE, so the table's owner is held to the policy too, unless it's a superuser.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ({ORG}) WITH CHECK ({ORG})"
        )


def downgrade() -> None:
    if not _is_postgres():
        return

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Dropping the role fails, on purpose, while the API is still connected as it.
    op.execute(f"DROP OWNED BY {APP_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {APP_ROLE}")
