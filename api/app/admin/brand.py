"""Facts, terms and assets as contract types. The engine calls these directly."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.models import Asset as AssetRow
from app.admin.models import Fact as FactRow
from app.admin.models import Term as TermRow
from app.contracts import Asset, DataClass, Fact, Role, Term

PROTECTED_CLASSES = {DataClass.confidential, DataClass.restricted}
PROTECTED_FACT_READERS = {Role.admin.value, Role.legal.value}


def list_facts(session: Session) -> list[Fact]:
    """Returns the newest version of every fact, including expired and protected ones.

    The engine needs all of them. Anything shown to a person goes through visible_facts.
    """
    rows = session.scalars(select(FactRow).order_by(FactRow.id, FactRow.version))
    newest = {row.id: row for row in rows}
    return [Fact.model_validate(row, from_attributes=True) for row in newest.values()]


def visible_facts(facts: Iterable[Fact], role: str) -> list[Fact]:
    """Leaves out confidential and restricted facts unless the role may read them."""
    if role in PROTECTED_FACT_READERS:
        return list(facts)
    return [fact for fact in facts if fact.data_class not in PROTECTED_CLASSES]


def list_terms(session: Session) -> list[Term]:
    rows = session.scalars(select(TermRow).order_by(TermRow.id))
    return [Term.model_validate(row, from_attributes=True) for row in rows]


def list_assets(session: Session) -> list[Asset]:
    rows = session.scalars(select(AssetRow).order_by(AssetRow.id))
    return [Asset.model_validate(row, from_attributes=True) for row in rows]
