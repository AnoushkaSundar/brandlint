"""row-level security on users, with a way in for the lookups made before the org is known

alapan_0006 locked every tenant table but this one, because signing in finds a user by
email, and each request finds its user by id, before any org is known. The policy here is
the same as the others, plus one way through: a transaction that sets app.auth to 'on'
(app.tenancy.rls.auth_lookup, used by those two lookups and nothing else) can read users
across orgs. Writes are held to the org rule only.

Only Postgres has Row-Level Security, so on any other database this does nothing.

Revision ID: anoushka_0008
Revises: alapan_0006
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "anoushka_0008"
down_revision: str | None = "alapan_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
ORG = "org_id = nullif(current_setting('app.org_id', true), '')::uuid"
AUTH = "current_setting('app.auth', true) = 'on'"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON users")
    op.execute(
        f"CREATE POLICY {POLICY} ON users USING ({ORG} OR {AUTH}) WITH CHECK ({ORG})"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON users")
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
