"""Runs the product migration for real, on SQLite, and checks it against the models."""

from pathlib import Path

import app.db
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from app.auth.models import Organization, User
from app.auth.orgs import DEMO_ORG_ID
from app.db import Base
from sqlalchemy import create_engine, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.test_models import PRODUCT_TABLES

API_DIR = Path(__file__).resolve().parents[1]
# The head before the organisations migration, and the revision under test.
PREVIOUS = "alapan_0004_finding_manifest"
REVISION = "anoushka_0006"


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setattr(app.db, "DATABASE_URL", url)
    app.db.get_engine.cache_clear()
    yield create_engine(url)
    app.db.get_engine.cache_clear()


@pytest.fixture
def alembic_config():
    config = Config()
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


def test_upgrade_creates_every_product_table(database, alembic_config):
    command.upgrade(alembic_config, REVISION)

    assert PRODUCT_TABLES <= set(inspect(database).get_table_names())


def test_the_migration_matches_the_models(database, alembic_config):
    command.upgrade(alembic_config, REVISION)

    product_tables = {
        name: table
        for name, table in Base.metadata.tables.items()
        if name in PRODUCT_TABLES
    }

    def only_product_tables(obj, name, kind, reflected, compare_to):
        return kind != "table" or name in product_tables

    with database.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "include_object": only_product_tables},
        )
        assert compare_metadata(context, Base.metadata) == []


def test_downgrade_removes_every_product_table(database, alembic_config):
    command.upgrade(alembic_config, REVISION)
    command.downgrade(alembic_config, "base")

    remaining = set(inspect(database).get_table_names())
    assert not PRODUCT_TABLES & remaining


def add_old_users(database, count=2):
    """Users as they were before organisations existed."""
    with database.begin() as connection:
        for number in range(count):
            connection.execute(
                text(
                    "INSERT INTO users (id, email, name, password_hash, role, tag, created_at) "
                    "VALUES (:id, :email, :name, 'hash', 'creator', NULL, '2026-01-01 00:00:00')"
                ),
                {
                    "id": f"u{number}",
                    "email": f"u{number}@x.y",
                    "name": f"User {number}",
                },
            )


def test_the_org_migration_puts_existing_users_in_the_demo_org(
    database, alembic_config
):
    command.upgrade(alembic_config, PREVIOUS)
    add_old_users(database)

    command.upgrade(alembic_config, REVISION)

    with Session(database) as session:
        orgs = session.scalars(select(Organization)).all()
        assert [(org.id, org.name, org.slug, org.kind, org.status) for org in orgs] == [
            (DEMO_ORG_ID, "Tarnhollow", "tarnhollow", "demo", "active")
        ]
        assert [user.org_id for user in session.scalars(select(User))] == [
            DEMO_ORG_ID
        ] * 2


def test_after_the_org_migration_a_user_needs_an_org(database, alembic_config):
    command.upgrade(alembic_config, REVISION)

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            insert(User.__table__).values(
                id="u", email="u@x.y", name="U", password_hash="h", role="creator"
            )
        )


def test_the_org_migration_has_an_index_on_users(database, alembic_config):
    command.upgrade(alembic_config, REVISION)

    indexes = {
        tuple(index["column_names"]) for index in inspect(database).get_indexes("users")
    }
    assert ("org_id",) in indexes


def test_the_org_migration_downgrades_and_keeps_the_users(database, alembic_config):
    command.upgrade(alembic_config, PREVIOUS)
    add_old_users(database)
    command.upgrade(alembic_config, REVISION)

    command.downgrade(alembic_config, PREVIOUS)

    inspector = inspect(database)
    assert "organizations" not in inspector.get_table_names()
    assert "org_id" not in {column["name"] for column in inspector.get_columns("users")}
    with database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == 2


def test_the_org_migration_can_run_again_after_a_downgrade(database, alembic_config):
    command.upgrade(alembic_config, REVISION)
    command.downgrade(alembic_config, PREVIOUS)
    add_old_users(database)

    command.upgrade(alembic_config, REVISION)

    with Session(database) as session:
        assert {user.org_id for user in session.scalars(select(User))} == {DEMO_ORG_ID}


def test_the_demo_org_id_in_the_migration_matches_the_app():
    migration = next((API_DIR / "migrations" / "versions").glob("anoushka_0006_*.py"))

    assert DEMO_ORG_ID in migration.read_text(encoding="utf-8")
