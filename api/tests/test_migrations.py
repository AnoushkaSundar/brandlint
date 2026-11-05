"""Runs the product migration for real, on SQLite, and checks it against the models."""

from pathlib import Path

import app.db
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from app.db import Base
from sqlalchemy import create_engine, inspect

from tests.test_models import PRODUCT_TABLES

API_DIR = Path(__file__).resolve().parents[1]
REVISION = "anoushka_0001"


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
