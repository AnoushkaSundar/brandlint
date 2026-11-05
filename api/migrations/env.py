"""Alembic environment. Reuses the app's shared engine + Base.

To let --autogenerate see tables, import the owning model modules below.
Each owner adds their import in their own migration PR, e.g.:

    import app.gateway.models   # noqa: F401  gateway_log, token_vault
    import app.engine.models    # noqa: F401  chunks, claim_units, findings, ...
    import app.content.models   # noqa: F401  Anoushka's tables

contracts/v1 ships the scaffolding only — no table modules exist yet.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app.db import Base, get_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import every owner's table modules so their tables register on Base.metadata
# for --autogenerate. Referenced in _TABLES below so linters see them as used.
import app.admin.models
import app.auth.models
import app.content.models
import app.engine.models
import app.gateway.models
import app.governance.models
import app.memory.models
import app.workflow.models

_TABLES = (
    app.admin.models,
    app.auth.models,
    app.content.models,
    app.engine.models,
    app.gateway.models,
    app.governance.models,
    app.memory.models,
    app.workflow.models,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(get_engine().url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
