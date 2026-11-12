"""Loads the demo brand into the tables: python -m app.admin.seed

Safe to run twice. A row that already exists is left alone, so an admin's edits survive.
"""

import json
import sys
from datetime import date
from typing import Any

from mocks.data import demo_dir
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.admin.models import Asset, Fact, Rule, Term
from app.auth import models as _auth_models  # noqa: F401  ingest_jobs references users
from app.auth.orgs import DEMO_ORG_ID, ensure_demo_org
from app.db import Base, get_sessionmaker
from app.tenancy import scoped_get


def _brand(name: str) -> list[dict[str, Any]]:
    return json.loads((demo_dir() / "brand" / name).read_text(encoding="utf-8"))


def _with_date(fact: dict[str, Any]) -> dict[str, Any]:
    valid_until = fact.get("valid_until")
    return {
        **fact,
        "valid_until": date.fromisoformat(valid_until) if valid_until else None,
    }


def _add_missing(
    session: Session, model: type[Base], records: list[dict[str, Any]], org_id: str
) -> int:
    key = [
        column.name for column in inspect(model).primary_key if column.name != "org_id"
    ]
    missing = [
        record
        for record in records
        if scoped_get(
            session, model, tuple(record[name] for name in key), org_id=org_id
        )
        is None
    ]
    session.add_all(model(org_id=org_id, **record) for record in missing)
    return len(missing)


def seed_brand(
    session: Session, *, rules: bool = True, org_id: str = DEMO_ORG_ID
) -> dict[str, int]:
    """Adds any missing demo brand rows to an org and returns how many of each were created.

    The demo org is the default. The org has to exist.

    Without rules, the rulebook starts empty, for a demo that begins by ingesting the
    guideline.
    """
    added = {
        "rules": _add_missing(session, Rule, _brand("rules.json"), org_id)
        if rules
        else 0,
        "facts": _add_missing(
            session, Fact, [_with_date(fact) for fact in _brand("facts.json")], org_id
        ),
        "terms": _add_missing(session, Term, _brand("terms.json"), org_id),
        "assets": _add_missing(session, Asset, _brand("assets.json"), org_id),
    }
    session.commit()
    return added


def main() -> None:
    with_rules = "--without-rules" not in sys.argv
    with get_sessionmaker()() as session:
        ensure_demo_org(session)
        added = seed_brand(session, rules=with_rules)
    print(
        "Added " + ", ".join(f"{count} {name}" for name, count in added.items()) + "."
    )


if __name__ == "__main__":
    main()
