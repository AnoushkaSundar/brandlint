"""Reset the demo workspace, and load the sample guidelines into any workspace.

Resetting deletes the demo org's content, reviews, findings and brand rows, then loads
the brand again. It keeps the people (so whoever clicked it stays signed in) and the audit
log. Only the Tarnhollow demo org can be reset: any other org is refused, so one click
can never wipe somebody's real workspace.
"""

import shutil

from sqlalchemy.orm import Session

from app.admin.seed import seed_brand
from app.auth.orgs import DEMO_ORG_ID
from app.auth.seed import seed_users
from app.content import storage
from app.db import Base
from app.tenancy import resolve_org, scoped_delete

# Not demo data: the accounts, and the record of what was done to them.
KEPT = {"users", "audit_log"}


class NotTheDemoOrg(PermissionError):
    """Only the demo workspace can be reset."""


def _tenant_models() -> list[type]:
    """Every model with an org column, children before the rows they refer to."""
    by_table = {
        mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers
    }
    return [
        by_table[table.name]
        for table in reversed(Base.metadata.sorted_tables)
        if "org_id" in table.c and table.name in by_table and table.name not in KEPT
    ]


def reset_demo(session: Session) -> dict[str, int]:
    """Deletes the demo org's data and loads the demo brand again. Returns the brand rows added."""
    org_id = str(resolve_org(session)).lower()
    if org_id != DEMO_ORG_ID:
        raise NotTheDemoOrg("Only the demo workspace can be reset.")

    for model in _tenant_models():
        session.execute(scoped_delete(session, model))
    session.commit()
    # Uploads live in the org's own folder. Files from before orgs existed stay where they are.
    shutil.rmtree(storage.stored_path(f"{org_id}/x").parent, ignore_errors=True)

    seed_users(session)
    return seed_brand(session, org_id=org_id)


def load_sample_guidelines(session: Session) -> dict[str, int]:
    """Copies the Tarnhollow guidelines into the caller's org as a starting point.

    Safe to repeat: a row the org already has is left alone, so its own edits survive.
    """
    return seed_brand(session, org_id=str(resolve_org(session)))
