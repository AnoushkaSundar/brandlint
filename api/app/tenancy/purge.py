"""Deleting an org's rows: the demo reset keeps some, the expiry job removes them all.

The session has to be bound to the org, so every delete goes through `scoped_delete` and,
under Row-Level Security, only ever sees that org's rows. No role that bypasses RLS is
needed for this.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Collection

from sqlalchemy.orm import Session

from app.db import Base
from app.tenancy.scoped import scoped_delete


def load_every_model() -> None:
    """Imports each app.*.models module, so the registry holds every table.

    The API does this by importing its routers. A script that runs on its own, like the
    expiry job, has not, and would otherwise see only the tables it happened to import.
    """
    package = importlib.import_module("app")
    for info in pkgutil.walk_packages(package.__path__, prefix="app."):
        if info.name.endswith(".models"):
            importlib.import_module(info.name)


def tenant_models(keep: Collection[str] = ()) -> list[type]:
    """Every model with an org column, children before the rows they refer to."""
    load_every_model()
    by_table = {
        mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers
    }
    models = [
        by_table[table.name]
        for table in reversed(Base.metadata.sorted_tables)
        if "org_id" in table.c and table.name in by_table and table.name not in keep
    ]
    # Many tables point at a person, and the database enforces some of those links that
    # the models don't declare. So people always go last.
    return sorted(models, key=lambda model: model.__tablename__ == "users")


def purge_org_data(session: Session, keep: Collection[str] = ()) -> None:
    """Deletes the bound org's rows from every tenant table except those named in `keep`."""
    for model in tenant_models(keep):
        session.execute(scoped_delete(session, model))
