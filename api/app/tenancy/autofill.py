"""Puts a new row in the caller's org, and refuses a new row for any other org.

This applies to a session that is bound to an org, which is a request after `current_org`.
A background job or a seed has no bound org and names the org itself. A row with no org
anywhere is never guessed: the column is NOT NULL, so the database refuses it.
"""

from __future__ import annotations

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.tenancy.errors import OrgMismatch
from app.tenancy.scoped import ORG_KEY, bound_org


@event.listens_for(Session, "before_flush")
def fill_the_org(session: Session, flush_context, instances) -> None:
    org = bound_org(session)
    if org is None:
        return
    for row in session.new:
        if ORG_KEY not in inspect(row).mapper.columns:
            continue
        given = getattr(row, ORG_KEY, None)
        if given is None:
            setattr(row, ORG_KEY, org)
        elif str(given).lower() != org.lower():
            raise OrgMismatch(
                f"Refusing to add a {type(row).__name__} for org {given} "
                f"from a request that belongs to org {org}."
            )
