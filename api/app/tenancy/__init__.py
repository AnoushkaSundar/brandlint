"""Tenant isolation: the scoped query helpers and the request's org.

Import from here: `from app.tenancy import scoped, scoped_get`. The request dependency
is `from app.tenancy.context import CurrentOrg`, kept apart so this package can be
imported by the auth code without a cycle. Importing this package also switches on the
rule that a request can only add rows to its own org.

See "Querying tenant data" in CLAUDE.md.
"""

from app.tenancy import autofill as autofill
from app.tenancy.errors import NoOrg, NotTenantModel, OrgMismatch, TenancyError
from app.tenancy.scoped import (
    bind_org,
    bound_org,
    org_criterion,
    resolve_org,
    scoped,
    scoped_delete,
    scoped_get,
    scoped_join,
    scoped_update,
)

__all__ = [
    "NoOrg",
    "NotTenantModel",
    "OrgMismatch",
    "TenancyError",
    "bind_org",
    "bound_org",
    "org_criterion",
    "resolve_org",
    "scoped",
    "scoped_delete",
    "scoped_get",
    "scoped_join",
    "scoped_update",
]
