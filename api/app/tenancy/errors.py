"""What can go wrong when tenant data is queried or written."""


class TenancyError(Exception):
    """Base for every tenancy refusal."""


class NotTenantModel(TenancyError, TypeError):
    """The model has no org_id, so it can't be scoped. It is either shared or not scoped yet."""


class NoOrg(TenancyError):
    """No org was given and none is bound to the session. Scoping by guessing would leak."""


class OrgMismatch(TenancyError):
    """A query or a new row names a different org from the one this request belongs to."""
