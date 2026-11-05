import os
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for the product tables (users, content, workflow, admin)."""


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


@lru_cache
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with session_factory()() as session:
        yield session
