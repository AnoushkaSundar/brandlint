"""Shared database layer: the single SQLAlchemy declarative Base, engine and
session factory that BOTH owners' table models build on.

Keeping one Base means Alembic sees every table through one metadata object.
Table models themselves live per owner (Alapan: api/app/engine, api/app/gateway,
etc.; Anoushka: api/app/auth, api/app/content, ...), each inheriting from Base.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://brandlint:brandlint@localhost:5432/brandlint",
)


class Base(DeclarativeBase):
    """Shared declarative base for every table in the app."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the engine lazily, so importing this module never requires a live
    DB or the psycopg driver (tests build their own engines)."""
    return create_engine(DATABASE_URL, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(), autoflush=False, expire_on_commit=False, class_=Session
    )


def get_session() -> Iterator[Session]:
    """FastAPI dependency: commit on clean exit, roll back on error, always close."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
