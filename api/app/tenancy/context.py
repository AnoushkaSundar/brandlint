"""The org of the current request: the signed-in user's, from the database."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.auth.dependencies import CurrentUser, SessionDep
from app.auth.models import Organization
from app.tenancy.scoped import bind_org


def current_org(user: CurrentUser, session: SessionDep) -> Organization:
    """The user's org, with the session tied to it for the rest of the request.

    `current_user` has already refused a suspended, expired or missing org. The org comes
    from the user's row and from nothing else: not a token claim, body, path, query or header.
    """
    bind_org(session, user.org_id)
    return session.get(Organization, user.org_id)


CurrentOrg = Annotated[Organization, Depends(current_org)]
