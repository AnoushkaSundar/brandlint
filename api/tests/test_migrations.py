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
ORGS = "anoushka_0006"
PRODUCT = "anoushka_0007"
REVISION = "alapan_0005"


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

    command.upgrade(alembic_config, ORGS)

    with Session(database) as session:
        orgs = session.scalars(select(Organization)).all()
        assert [(org.id, org.name, org.slug, org.kind, org.status) for org in orgs] == [
            (DEMO_ORG_ID, "Tarnhollow", "tarnhollow", "demo", "active")
        ]
        assert [user.org_id for user in session.scalars(select(User))] == [
            DEMO_ORG_ID
        ] * 2


def test_after_the_org_migration_a_user_needs_an_org(database, alembic_config):
    command.upgrade(alembic_config, ORGS)

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            insert(User.__table__).values(
                id="u", email="u@x.y", name="U", password_hash="h", role="creator"
            )
        )


def test_the_org_migration_has_an_index_on_users(database, alembic_config):
    command.upgrade(alembic_config, ORGS)

    indexes = {
        tuple(index["column_names"]) for index in inspect(database).get_indexes("users")
    }
    assert ("org_id",) in indexes


def test_the_org_migration_downgrades_and_keeps_the_users(database, alembic_config):
    command.upgrade(alembic_config, PREVIOUS)
    add_old_users(database)
    command.upgrade(alembic_config, ORGS)

    command.downgrade(alembic_config, PREVIOUS)

    inspector = inspect(database)
    assert "organizations" not in inspector.get_table_names()
    assert "org_id" not in {column["name"] for column in inspector.get_columns("users")}
    with database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == 2


def test_the_org_migration_can_run_again_after_a_downgrade(database, alembic_config):
    command.upgrade(alembic_config, ORGS)
    command.downgrade(alembic_config, PREVIOUS)
    add_old_users(database)

    command.upgrade(alembic_config, ORGS)

    with Session(database) as session:
        assert {user.org_id for user in session.scalars(select(User))} == {DEMO_ORG_ID}


def test_the_demo_org_id_in_the_migration_matches_the_app():
    migration = next((API_DIR / "migrations" / "versions").glob("anoushka_0006_*.py"))

    assert DEMO_ORG_ID in migration.read_text(encoding="utf-8")


# Block 3: the product tables

ORG_TABLES = [
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
]
NOW = "'2026-01-01 00:00:00'"
DEMO_HEX = DEMO_ORG_ID.replace("-", "")
OLD_ROWS = [
    f"INSERT INTO users (id, email, name, password_hash, role, tag, created_at, org_id) VALUES ('u1', 'u@x.y', 'U', 'h', 'creator', NULL, {NOW}, '{DEMO_HEX}')",
    f"INSERT INTO content (id, title, channel, source, data_class, state, creator_id, created_at) VALUES ('c1', 'T', 'blog', 's', 'public', 'draft', 'u1', {NOW})",
    f"INSERT INTO content_versions (id, content_id, version, text, fixes_applied, created_by, created_at) VALUES ('v1', 'c1', 1, 't', 0, 'u1', {NOW})",
    f"INSERT INTO reviews (id, content_version_id, engine_review_id, channel, rulebook_version, created_at) VALUES ('r1', 'v1', 'e1', 'blog', 1, {NOW})",
    f"INSERT INTO review_state_log (id, content_id, from_state, to_state, actor_id, created_at) VALUES ('l1', 'c1', 'draft', 'ai_review', 'u1', {NOW})",
    f"INSERT INTO decisions (id, review_id, finding_id, actor_id, role, action, status, created_at) VALUES ('d1', 'r1', 'f1', 'u1', 'creator', 'override', 'override_pending', {NOW})",
    f"INSERT INTO fix_offers (id, review_id, finding_id, attempt, original, suggested, diff, created_at) VALUES ('o1', 'r1', 'f1', 1, 'a', 'b', 'c', {NOW})",
    f"INSERT INTO comments (id, content_version_id, finding_id, author_id, body, mentions, created_at) VALUES ('m1', 'v1', NULL, 'u1', 'b', '[]', {NOW})",
    f"INSERT INTO audit_log (id, actor_id, role, action, target_type, target_id, created_at) VALUES ('a1', 'u1', 'admin', 'x', 'fact', 'F-001', {NOW})",
    "INSERT INTO rules (id, version, type, text, clause_ref, severity, channel_scope, status) VALUES ('R1', 1, 'judgment', 't', 'c1', 'low', '[]', 'approved')",
    "INSERT INTO rules (id, version, type, text, clause_ref, severity, channel_scope, status) VALUES ('R1', 2, 'judgment', 't2', 'c1', 'low', '[]', 'approved')",
    "INSERT INTO facts (id, version, statement, value, source_doc, owner, data_class) VALUES ('F-001', 1, 's', 'v', 'd', 'o', 'public')",
    "INSERT INTO terms (id, preferred, banned) VALUES ('T-001', 'p', '[]')",
    "INSERT INTO assets (id, kind, file_ref, meta) VALUES ('A-001', 'palette', '', '{}')",
    f"INSERT INTO ingest_jobs (id, file_ref, status, created_by, created_at) VALUES ('j1', 'g.pdf', 'done', 'u1', {NOW})",
    f"INSERT INTO gaps (id, review_id, \"check\", text, explanation, created_at) VALUES ('g1', 'e1', 'tone', 't', 'e', {NOW})",
]


def add_old_product_rows(database):
    with database.begin() as connection:
        for statement in OLD_ROWS:
            connection.execute(text(statement))


def rows_in_the_demo_org(database, table):
    import sqlalchemy as sa

    reference = sa.table(table, sa.column("org_id", sa.Uuid(as_uuid=False)))
    with database.connect() as connection:
        return (
            connection.scalar(sa.select(sa.func.count()).select_from(reference)),
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(reference)
                .where(reference.c.org_id == DEMO_ORG_ID)
            ),
        )


def test_the_product_migration_puts_every_existing_row_in_the_demo_org(
    database, alembic_config
):
    command.upgrade(alembic_config, ORGS)
    add_old_product_rows(database)

    command.upgrade(alembic_config, PRODUCT)

    for table in ORG_TABLES:
        total, in_demo = rows_in_the_demo_org(database, table)
        assert total > 0, f"{table} had no rows to migrate"
        assert in_demo == total, (
            f"{table}: {in_demo} of {total} rows are in the demo org"
        )


@pytest.mark.parametrize("table", ORG_TABLES)
def test_after_the_product_migration_org_id_is_required_and_a_foreign_key(
    database, alembic_config, table
):
    command.upgrade(alembic_config, PRODUCT)
    inspector = inspect(database)

    column = next(c for c in inspector.get_columns(table) if c["name"] == "org_id")
    assert column["nullable"] is False
    assert any(
        fk["constrained_columns"] == ["org_id"]
        and fk["referred_table"] == "organizations"
        for fk in inspector.get_foreign_keys(table)
    )


@pytest.mark.parametrize(
    ("table", "key"),
    [
        ("rules", ["org_id", "id", "version"]),
        ("facts", ["org_id", "id", "version"]),
        ("terms", ["org_id", "id"]),
        ("assets", ["org_id", "id"]),
    ],
)
def test_rules_facts_terms_and_assets_are_keyed_per_org(
    database, alembic_config, table, key
):
    command.upgrade(alembic_config, PRODUCT)

    assert inspect(database).get_pk_constraint(table)["constrained_columns"] == key


def test_two_orgs_can_hold_the_same_rule_after_the_migration(database, alembic_config):
    command.upgrade(alembic_config, PRODUCT)
    other = "11111111-1111-4111-8111-111111111111".replace("-", "")
    with database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organizations (id, name, slug, kind, created_at, status) "
                f"VALUES ('{other}', 'Other', 'other', 'sandbox', {NOW}, 'active')"
            )
        )
        for org in (DEMO_HEX, other):
            connection.execute(
                text(
                    "INSERT INTO rules (org_id, id, version, type, text, clause_ref, severity, channel_scope, status) "
                    f"VALUES ('{org}', 'R1', 1, 'judgment', 't', 'c1', 'low', '[]', 'approved')"
                )
            )

    with database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM rules")) == 2


def test_the_product_migration_downgrades_and_keeps_the_rows(database, alembic_config):
    command.upgrade(alembic_config, ORGS)
    add_old_product_rows(database)
    command.upgrade(alembic_config, PRODUCT)

    command.downgrade(alembic_config, ORGS)

    inspector = inspect(database)
    for table in ORG_TABLES:
        assert "org_id" not in {c["name"] for c in inspector.get_columns(table)}, table
    assert inspector.get_pk_constraint("rules")["constrained_columns"] == [
        "id",
        "version",
    ]
    assert inspector.get_pk_constraint("terms")["constrained_columns"] == ["id"]
    with database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM rules")) == 2
        assert connection.scalar(text("SELECT count(*) FROM content")) == 1


def test_the_product_migration_can_run_again_after_a_downgrade(
    database, alembic_config
):
    command.upgrade(alembic_config, PRODUCT)
    command.downgrade(alembic_config, ORGS)
    add_old_product_rows(database)

    command.upgrade(alembic_config, PRODUCT)

    assert rows_in_the_demo_org(database, "rules") == (2, 2)


# Block 4: the engine, memory, gateway and governance tables

AFTER_PRODUCT = PRODUCT
AI_TABLES = [
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
AI_ROWS = [
    "INSERT INTO chunks (id, content_version_id, ordinal, kind, text, content_hash, data_class, style) VALUES ('ch1', 'v1', 0, 'paragraph', 't', 'h', 'public', NULL)",
    f"INSERT INTO claim_units (id, review_id, content_version_id, normalized_claim, span_refs, depends_on, created_at) VALUES ('cu1', 'e1', 'v1', 'c', '[]', '[]', {NOW})",
    f"INSERT INTO findings (id, review_id, content_version_id, unit_type, spans, \"check\", tier, verdict, severity, confidence, rule_id, rule_version, fact_ids, cited_text, explanation, trace, ai_generated, models_used, vote, fix_available, status, manifest, created_at) VALUES ('f1', 'e1', 'v1', 'chunk', '[]', 'tone', 1, 'UNSURE', 'low', 0.5, 'R1', 1, '[]', 'c', 'e', '{{}}', 0, '[]', NULL, 0, 'open', NULL, {NOW})",
    f"INSERT INTO review_cache (id, cache_key, unit_type, verdict, payload, depends_on, valid_until, manifest, created_at) VALUES ('rc1', 'key1', 'chunk', 'PASS', '{{}}', '[]', NULL, '{{}}', {NOW})",
    f"INSERT INTO edges (id, type, src_type, src_id, dst_type, dst_id, meta, created_at) VALUES ('ed1', 'CITES', 'Claim', 'cu1', 'Fact', 'F-001', '{{}}', {NOW})",
    f"INSERT INTO gateway_log (id, created_at, purpose, data_class, rule_ids, provider, model, route, masked, review_id, status, latency_ms, error) VALUES ('gl1', {NOW}, 'classify', 'public', '[]', NULL, 'm', 'litellm', NULL, 'e1', 'ok', 5, NULL)",
    f"INSERT INTO token_vault (id, scope, token, value, entity, created_at) VALUES ('tv1', 'e1', '[PRODUCT_1]', 'Bluewren', 'PRODUCT', {NOW})",
    f"INSERT INTO proposals (id, rule_id, kind, current, suggested, evidence, eval, status, created_at) VALUES ('p1', 'R1', 'amendment', 'a', 'b', '{{}}', NULL, 'pending', {NOW})",
    f"INSERT INTO spot_checks (id, content_id, review_id, sampled_at, reviewer_id, result) VALUES ('sc1', 'c1', 'e1', {NOW}, NULL, NULL)",
    f"INSERT INTO eval_runs (id, kind, precision, recall, false_flag_rate, attack_success_rate, passed, details, created_at) VALUES ('ev1', 'gate', 1.0, 1.0, 0.0, 0.0, 1, '{{}}', {NOW})",
]


def add_old_ai_rows(database):
    with database.begin() as connection:
        for statement in AI_ROWS:
            connection.execute(text(statement))


def test_the_ai_migration_puts_every_existing_row_in_the_demo_org(
    database, alembic_config
):
    command.upgrade(alembic_config, AFTER_PRODUCT)
    add_old_ai_rows(database)

    command.upgrade(alembic_config, REVISION)

    for table in AI_TABLES:
        total, in_demo = rows_in_the_demo_org(database, table)
        assert total > 0, f"{table} had no rows to migrate"
        assert in_demo == total, f"{table}: {in_demo} of {total} rows are in the demo org"


@pytest.mark.parametrize("table", AI_TABLES)
def test_after_the_ai_migration_org_id_is_required_and_a_foreign_key(
    database, alembic_config, table
):
    command.upgrade(alembic_config, REVISION)
    inspector = inspect(database)

    column = next(c for c in inspector.get_columns(table) if c["name"] == "org_id")
    assert column["nullable"] is False
    assert any(
        fk["constrained_columns"] == ["org_id"]
        and fk["referred_table"] == "organizations"
        for fk in inspector.get_foreign_keys(table)
    )


def test_edges_are_keyed_per_org(database, alembic_config):
    command.upgrade(alembic_config, REVISION)

    assert inspect(database).get_pk_constraint("edges")["constrained_columns"] == [
        "org_id",
        "id",
    ]


def test_the_ai_migration_matches_the_models(database, alembic_config):
    command.upgrade(alembic_config, REVISION)
    tables = {
        name: table
        for name, table in Base.metadata.tables.items()
        if name in AI_TABLES
    }

    def only_ai_tables(obj, name, kind, reflected, compare_to):
        return kind != "table" or name in tables

    with database.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "include_object": only_ai_tables},
        )
        assert compare_metadata(context, Base.metadata) == []


def test_the_ai_migration_downgrades_and_keeps_the_rows(database, alembic_config):
    command.upgrade(alembic_config, AFTER_PRODUCT)
    add_old_ai_rows(database)
    command.upgrade(alembic_config, REVISION)

    command.downgrade(alembic_config, AFTER_PRODUCT)

    inspector = inspect(database)
    for table in AI_TABLES:
        assert "org_id" not in {c["name"] for c in inspector.get_columns(table)}, table
    assert inspector.get_pk_constraint("edges")["constrained_columns"] == ["id"]
    with database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM findings")) == 1
        assert connection.scalar(text("SELECT count(*) FROM edges")) == 1


def test_the_ai_migration_can_run_again_after_a_downgrade(database, alembic_config):
    command.upgrade(alembic_config, REVISION)
    command.downgrade(alembic_config, AFTER_PRODUCT)
    add_old_ai_rows(database)

    command.upgrade(alembic_config, REVISION)

    assert rows_in_the_demo_org(database, "findings") == (1, 1)
