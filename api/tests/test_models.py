"""The product tables from docs/contracts.md. There's no Postgres in CI, so this also
compiles each table for Postgres to catch anything that only works on SQLite.
"""

from app.admin import models as admin_models  # noqa: F401
from app.auth import models as auth_models  # noqa: F401
from app.content import models as content_models  # noqa: F401
from app.db import Base
from app.workflow import models as workflow_models  # noqa: F401
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

PRODUCT_TABLES = {
    "users",
    "content",
    "content_versions",
    "reviews",
    "review_state_log",
    "decisions",
    "comments",
    "audit_log",
    "rules",
    "facts",
    "terms",
    "assets",
    "ingest_jobs",
    "gaps",
}


def columns(table: str) -> set[str]:
    return {column.name for column in Base.metadata.tables[table].columns}


def test_every_product_table_is_defined():
    assert PRODUCT_TABLES <= set(Base.metadata.tables)


def test_every_table_compiles_for_postgres():
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE {table.name}" in ddl


def test_tables_hold_every_contract_field():
    assert {
        "id",
        "version",
        "type",
        "text",
        "clause_ref",
        "severity",
        "channel_scope",
        "status",
        "supersedes",
    } == columns("rules")
    assert {
        "id",
        "statement",
        "value",
        "source_doc",
        "owner",
        "valid_until",
        "data_class",
        "version",
    } == columns("facts")
    assert {"id", "preferred", "banned", "renamed_from"} == columns("terms")
    assert {"id", "kind", "file_ref", "meta"} == columns("assets")
    assert {
        "id",
        "finding_id",
        "actor_id",
        "role",
        "action",
        "reason",
        "created_at",
    } == columns("decisions")
    assert {"id", "review_id", "check", "text", "explanation", "created_at"} == columns(
        "gaps"
    )


def test_reviews_pin_the_rulebook_version():
    column = Base.metadata.tables["reviews"].columns["rulebook_version"]
    assert column.nullable is False


def test_audit_log_records_who_did_what():
    assert {
        "actor_id",
        "role",
        "action",
        "target_type",
        "target_id",
        "before",
        "after",
        "rulebook_version",
        "created_at",
    } <= columns("audit_log")


def test_decisions_do_not_depend_on_the_engine_tables():
    column = Base.metadata.tables["decisions"].columns["finding_id"]
    assert not column.foreign_keys


def test_timestamps_keep_their_time_zone():
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if column.name == "created_at":
                assert column.type.timezone is True
