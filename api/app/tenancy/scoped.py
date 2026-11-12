"""The one correct way to query tenant data.

Every query on a tenant model goes through these, so the org filter can't be forgotten
or written by hand a little differently each time. They refuse a model that has no
`org_id`, so a table that isn't scoped yet can't be queried as if it were.

The org is the one bound to the session for this request (see `current_org`), or one
passed as `org_id` by a background job. Passing an org that differs from the bound one
is an error, never a way to look at another org.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    ColumnElement,
    Delete,
    Select,
    Update,
    and_,
    delete,
    inspect,
    select,
    update,
)
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.orm import Mapper, Session

from app.tenancy.errors import NoOrg, NotTenantModel, OrgMismatch

ORG_KEY = "org_id"


def bind_org(session: Session, org_id: str) -> None:
    """Ties the session to one org for the rest of its life. The request context does this."""
    session.info[ORG_KEY] = str(org_id)


def bound_org(session: Session) -> str | None:
    return session.info.get(ORG_KEY)


def resolve_org(session: Session, org_id: str | None = None) -> str:
    """The org a query is for: the one given, or the one bound to the session."""
    bound = bound_org(session)
    if org_id is None:
        if bound is None:
            raise NoOrg("No org is bound to this session and none was given.")
        return bound
    if bound is not None and str(org_id).lower() != bound.lower():
        raise OrgMismatch(f"This session belongs to org {bound}, not {org_id}.")
    return str(org_id)


def tenant_mapper(model: type) -> Mapper:
    """The mapper of a model that has an org_id, or a refusal."""
    try:
        mapper = inspect(model)
    except NoInspectionAvailable:
        raise NotTenantModel(f"{model!r} is not a mapped model.") from None
    if ORG_KEY not in mapper.columns:
        raise NotTenantModel(
            f"{model.__name__} has no org_id, so it isn't tenant data and can't be scoped. "
            "Shared tables are queried directly, and tables that don't have org_id yet "
            "get it in their block of docs/multitenancy.md."
        )
    return mapper


def org_criterion(
    session: Session, model: type, org_id: str | None = None
) -> ColumnElement[bool]:
    """`Model.org_id == the org`, for the places a whole query isn't the right shape."""
    tenant_mapper(model)
    return model.org_id == resolve_org(session, org_id)


def scoped(
    session: Session, model: type, *entities: Any, org_id: str | None = None
) -> Select:
    """`select(model)` limited to the org. Pass columns or aggregates to select those instead.

    Build on it as usual: `scoped(session, Content).where(...).order_by(...)`.
    """
    criterion = org_criterion(session, model, org_id)
    if entities:
        return select(*entities).select_from(model).where(criterion)
    return select(model).where(criterion)


def scoped_join(
    statement: Select,
    session: Session,
    model: type,
    onclause: ColumnElement[bool],
    *,
    outer: bool = False,
    org_id: str | None = None,
) -> Select:
    """Joins another tenant model and keeps only its rows in the org.

    The org test goes in the join condition, so a row of another org never joins in, and
    an outer join still keeps the left side.
    """
    criterion = org_criterion(session, model, org_id)
    return statement.join(model, and_(onclause, criterion), isouter=outer)


def scoped_get(
    session: Session, model: type, ident: Any, *, org_id: str | None = None
) -> Any | None:
    """The row with this key if it belongs to the org, otherwise None.

    Another org's row and a row that doesn't exist look the same, so an id can't be used
    to find out whether it exists. `Session.get` can't do this: it ignores the org.

    `ident` is the key without the org, as a single value or a tuple in column order.
    """
    mapper = tenant_mapper(model)
    keys = [column for column in mapper.primary_key if column.name != ORG_KEY]
    values = tuple(ident) if isinstance(ident, (tuple, list)) else (ident,)
    if len(values) != len(keys):
        raise ValueError(
            f"{model.__name__} has a key of {len(keys)} values, got {len(values)}."
        )
    statement = scoped(session, model, org_id=org_id).where(
        *[column == value for column, value in zip(keys, values, strict=True)]
    )
    return session.scalars(statement).first()


def scoped_update(
    session: Session, model: type, *, org_id: str | None = None
) -> Update:
    """`update(model)` limited to the org."""
    return update(model).where(org_criterion(session, model, org_id))


def scoped_delete(
    session: Session, model: type, *, org_id: str | None = None
) -> Delete:
    """`delete(model)` limited to the org."""
    return delete(model).where(org_criterion(session, model, org_id))
