"""Row-Level Security: the database refuses another org's rows, whatever the app forgets.

The first half runs everywhere. The second half needs a real Postgres server, because
SQLite has no Row-Level Security: set RLS_TEST_DATABASE_URL to a superuser URL, such as
postgresql+psycopg://user:pw@host:5432/postgres. Each test run builds a scratch database
and a role of its own, and removes them again.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from app.content.models import Content
from app.tenancy import bind_org, org_sessions, rls
from app.tenancy.rls import auth_lookup
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.tenancy.inventory import TENANT_TABLES

API_DIR = Path(__file__).resolve().parents[1]
MIGRATION = API_DIR / "migrations" / "versions" / "alapan_0006_row_level_security.py"
ORG_A = "00000000-0000-4000-8000-0000000000a1"
ORG_B = "00000000-0000-4000-8000-0000000000b2"


def migration_module():
    spec = importlib.util.spec_from_file_location("alapan_0006", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


# --- Runs everywhere ---------------------------------------------------------------------


def later_rls_tables() -> set[str]:
    """Tables that migrations after alapan_0006 lock, each naming them in RLS_TABLES."""
    found: set[str] = set()
    for path in sorted((API_DIR / "migrations" / "versions").glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        found |= set(getattr(module, "RLS_TABLES", []))
    return found


def test_the_migrations_cover_every_tenant_table():
    # alapan_0006 locks all but users, and the migrations after it lock users and the rest.
    locked = set(migration_module().TENANT_TABLES) | later_rls_tables() | {"users"}
    assert locked == set(TENANT_TABLES)


def test_the_migration_leaves_an_other_database_alone(tmp_path, monkeypatch):
    import app.db

    url = f"sqlite:///{(tmp_path / 'rls.db').as_posix()}"
    monkeypatch.setattr(app.db, "DATABASE_URL", url)
    app.db.get_engine.cache_clear()
    try:
        command.upgrade(alembic_config(), "head")
        command.downgrade(alembic_config(), "base")
    finally:
        app.db.get_engine.cache_clear()


@pytest.fixture()
def sessions(monkeypatch):
    """A SQLite session whose `apply` is recorded, because SQLite can't run it."""
    told: list[str] = []
    monkeypatch.setattr(rls, "apply", lambda connection, org: told.append(org))
    engine = create_engine("sqlite://")
    yield SimpleNamespace(told=told, engine=engine)
    engine.dispose()


def ping(session: Session) -> None:
    session.execute(text("SELECT 1"))


def test_a_session_with_no_org_tells_the_database_nothing(sessions):
    with Session(sessions.engine) as session:
        ping(session)
    assert sessions.told == []


def test_a_bound_session_tells_the_database_when_it_begins(sessions):
    with Session(sessions.engine) as session:
        bind_org(session, ORG_A)
        assert sessions.told == []  # nothing has begun yet
        ping(session)
    assert sessions.told == [ORG_A]


def test_every_new_transaction_is_told_not_only_the_first(sessions):
    with Session(sessions.engine) as session:
        bind_org(session, ORG_A)
        ping(session)
        session.commit()
        ping(session)
    assert sessions.told == [ORG_A, ORG_A]


def test_binding_after_a_transaction_began_tells_it_at_once(sessions):
    with Session(sessions.engine) as session:
        ping(session)  # the user lookup, before the org is known
        assert sessions.told == []
        bind_org(session, ORG_A)
        assert ORG_A in sessions.told


def test_apply_does_nothing_on_a_database_without_rls():
    calls = []
    engine = create_engine("sqlite://")
    event.listen(engine, "before_cursor_execute", lambda *args: calls.append(args[2]))
    with engine.connect() as connection:
        rls.apply(connection, ORG_A)
    assert calls == []


# --- Needs a real Postgres ---------------------------------------------------------------

ADMIN_URL = os.environ.get("RLS_TEST_DATABASE_URL")
postgres = pytest.mark.skipif(
    not ADMIN_URL, reason="needs Postgres: set RLS_TEST_DATABASE_URL to a superuser URL"
)


def build_database(monkeypatch: pytest.MonkeyPatch):
    """A migrated scratch database, its owner and app-role engines, and a cleanup."""
    suffix = uuid.uuid4().hex[:8]
    name, role, password = f"rls_{suffix}", f"rls_app_{suffix}", f"pw_{suffix}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {name}"))
    base = make_url(ADMIN_URL).set(database=name)
    owner_url = base.render_as_string(hide_password=False)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", owner_url)
    monkeypatch.setenv("APP_DB_ROLE", role)
    monkeypatch.setenv("APP_DB_PASSWORD", password)
    command.upgrade(alembic_config(), "head")

    owner = create_engine(owner_url)
    app_url = base.set(username=role, password=password)
    app = create_engine(app_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    seed(owner)

    def drop() -> None:
        app.dispose()
        owner.dispose()
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
            connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
        admin.dispose()

    return SimpleNamespace(
        owner=owner, app=app, role=role, name=name, drop=drop, config=alembic_config()
    )


def seed(owner) -> None:
    """Two orgs with a row each in four tables, written as the owner, who bypasses RLS."""
    with owner.begin() as connection:
        for org, letter in ((ORG_A, "a"), (ORG_B, "b")):
            connection.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, kind, created_at, status) "
                    "VALUES (:org, :name, :slug, 'sandbox', now(), 'active')"
                ),
                {"org": org, "name": f"Org {letter}", "slug": f"org-{letter}"},
            )
            connection.execute(
                text(
                    "INSERT INTO users (id, email, name, password_hash, role, created_at, org_id) "
                    "VALUES (:id, :email, 'Person', 'x', 'creator', now(), :org)"
                ),
                {"id": f"user-{letter}", "email": f"{letter}@x.y", "org": org},
            )
            connection.execute(
                text(
                    "INSERT INTO content (id, title, channel, source, data_class, state, "
                    "creator_id, created_at, org_id) VALUES (:id, :title, 'blog', 'agency', "
                    "'public', 'draft', :user, now(), :org)"
                ),
                {"id": f"content-{letter}", "title": f"Piece {letter}", "user": f"user-{letter}", "org": org},
            )
            connection.execute(
                text(
                    "INSERT INTO edges (id, type, src_type, src_id, dst_type, dst_id, org_id) "
                    "VALUES (:id, 'CITES', 'Claim', 'c', 'Fact', 'F-1', :org)"
                ),
                {"id": f"edge-{letter}", "org": org},
            )
            connection.execute(
                text(
                    "INSERT INTO gateway_log (id, purpose, data_class, rule_ids, route, status, org_id) "
                    "VALUES (:id, 'classify', 'public', '[]', 'litellm', 'ok', :org)"
                ),
                {"id": f"log-{letter}", "org": org},
            )
            connection.execute(
                text("INSERT INTO eval_runs (id, kind, org_id) VALUES (:id, 'gate', :org)"),
                {"id": f"eval-{letter}", "org": org},
            )


@pytest.fixture(scope="module")
def db():
    monkeypatch = pytest.MonkeyPatch()
    built = build_database(monkeypatch)
    yield built
    built.drop()
    monkeypatch.undo()


SEEDED = ["content", "edges", "gateway_log", "eval_runs"]


def as_org(engine, org: str | None):
    """A session on the app role. With no org it is exactly what forgetting to bind is."""
    session = Session(engine)
    if org is not None:
        bind_org(session, org)
    return session


def count(session: Session, table: str) -> int:
    return session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


@postgres
def test_the_app_role_cannot_bypass_security(db):
    with db.owner.connect() as connection:
        row = connection.execute(
            text("SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = :r"),
            {"r": db.role},
        ).one()
        owned = connection.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = :r"),
            {"r": db.role},
        ).scalar_one()
    assert tuple(row) == (False, False, True)
    assert owned == 0


@postgres
def test_every_tenant_table_is_locked(db):
    with db.owner.connect() as connection:
        with_org = {
            r[0]
            for r in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'org_id'"
                )
            )
        }
        locked = {
            r[0]
            for r in connection.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relkind = 'r' "
                    "AND relrowsecurity AND relforcerowsecurity"
                )
            )
        }
        with_policy = {
            r[0] for r in connection.execute(text("SELECT tablename FROM pg_policies"))
        }
    assert with_org - locked == set()
    assert with_org - with_policy == set()
    assert locked <= with_org


@postgres
def test_a_request_that_never_named_its_org_sees_nothing(db):
    with as_org(db.app, None) as session:
        for table in migration_module().TENANT_TABLES:
            assert count(session, table) == 0, table


@postgres
@pytest.mark.parametrize("table", SEEDED)
def test_each_org_sees_only_its_own_rows(db, table):
    for org in (ORG_A, ORG_B):
        with as_org(db.app, org) as session:
            assert count(session, table) == 1
            assert session.execute(text(f"SELECT org_id::text FROM {table}")).scalar_one() == org


@postgres
def test_a_forgotten_filter_still_returns_only_the_orgs_rows(db):
    """The point of the lock: a query with no org filter at all, on a bound session."""
    with as_org(db.app, ORG_A) as session:
        rows = session.scalars(select(Content)).all()
    assert [row.org_id for row in rows] == [ORG_A]


@postgres
def test_the_org_survives_a_commit_in_the_same_session(db):
    with as_org(db.app, ORG_A) as session:
        assert count(session, "content") == 1
        session.commit()
        assert count(session, "content") == 1
        assert session.execute(text("SELECT org_id::text FROM content")).scalar_one() == ORG_A


@postgres
def test_binding_after_the_first_query_takes_effect_at_once(db):
    """Signing in reads the user before the org is known, then the request binds it."""
    with as_org(db.app, None) as session:
        session.execute(text("SELECT 1"))
        assert count(session, "content") == 0
        bind_org(session, ORG_B)
        assert session.execute(text("SELECT org_id::text FROM content")).scalar_one() == ORG_B


@postgres
def test_an_orgs_setting_never_reaches_the_next_user_of_the_connection(db):
    """The pool holds one connection, so both sessions use the same one."""
    with as_org(db.app, ORG_A) as session:
        assert count(session, "content") == 1
    with as_org(db.app, None) as session:
        assert count(session, "content") == 0
        assert session.execute(text("SELECT current_setting('app.org_id', true)")).scalar_one() in (None, "")


@postgres
def test_the_database_refuses_a_row_for_another_org(db):
    with as_org(db.app, ORG_A) as session, pytest.raises(DBAPIError, match="row-level security"):
        session.execute(
            text(
                "INSERT INTO edges (id, type, src_type, src_id, dst_type, dst_id, org_id) "
                "VALUES ('sneaky', 'CITES', 'Claim', 'c', 'Fact', 'F-1', :other)"
            ),
            {"other": ORG_B},
        )


@postgres
def test_a_row_with_no_org_set_cannot_be_written(db):
    with as_org(db.app, None) as session, pytest.raises(DBAPIError, match="row-level security"):
        session.execute(
            text("INSERT INTO eval_runs (id, kind, org_id) VALUES ('orphan', 'gate', :org)"),
            {"org": ORG_A},
        )


@postgres
def test_another_orgs_rows_cannot_be_changed_or_deleted(db):
    with as_org(db.app, ORG_A) as session:
        changed = session.execute(text("UPDATE edges SET type = 'HIJACKED' WHERE id = 'edge-b'"))
        deleted = session.execute(text("DELETE FROM content WHERE id = 'content-b'"))
        assert (changed.rowcount, deleted.rowcount) == (0, 0)
        session.rollback()
    with db.owner.connect() as connection:
        assert connection.execute(text("SELECT type FROM edges WHERE id = 'edge-b'")).scalar_one() == "CITES"
        assert connection.execute(text("SELECT count(*) FROM content WHERE id = 'content-b'")).scalar_one() == 1


@postgres
def test_a_background_session_sees_only_its_org(db):
    """A review runs in a thread with its own sessions, bound by org_sessions."""
    seen: dict[str, int] = {}

    def work(org: str) -> None:
        with org_sessions(lambda: Session(db.app), org)() as session:
            seen[org] = count(session, "content")
            session.commit()
            seen[org + "-after"] = count(session, "content")

    threads = [threading.Thread(target=work, args=(org,)) for org in (ORG_A, ORG_B)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert seen == {ORG_A: 1, ORG_A + "-after": 1, ORG_B: 1, ORG_B + "-after": 1}


@postgres
def test_users_are_locked_except_inside_an_auth_lookup(db):
    """Sign-in looks a user up before any org is known; nothing else may read across orgs."""
    with as_org(db.app, None) as session:
        assert count(session, "users") == 0
    with as_org(db.app, ORG_A) as session:
        assert count(session, "users") == 1  # a forgotten filter still sees only its org
    with as_org(db.app, None) as session:
        with auth_lookup(session):
            assert count(session, "users") == 2
        assert count(session, "users") == 0  # and the way in closes when the block ends


@postgres
def test_the_migration_downgrades_and_upgrades_again(monkeypatch):
    built = build_database(monkeypatch)
    try:
        built.app.dispose()  # the role can't be dropped while it is connected
        command.downgrade(built.config, "alapan_0005")
        with built.owner.connect() as connection:
            policies = connection.execute(text("SELECT count(*) FROM pg_policies")).scalar_one()
            locked = connection.execute(
                text("SELECT count(*) FROM pg_class WHERE relkind = 'r' AND relrowsecurity")
            ).scalar_one()
            role = connection.execute(
                text("SELECT count(*) FROM pg_roles WHERE rolname = :r"), {"r": built.role}
            ).scalar_one()
        assert (policies, locked, role) == (0, 0, 0)

        command.upgrade(built.config, "head")
        with built.owner.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM pg_policies")).scalar_one() == len(
                TENANT_TABLES
            )
    finally:
        built.drop()
