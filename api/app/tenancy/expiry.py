"""Deletes sandbox workspaces that have expired, with their data and uploaded files.

Run it on a schedule: `python -m app.tenancy.expiry` (see deploy/README.md). Only a
`sandbox` org with an `expires_at` in the past is touched, so the demo org never is. Each
org is deleted in its own transaction, bound to that org, so under Row-Level Security the
job sees nothing but the org it is deleting.
"""

from __future__ import annotations

import shutil
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.defaults import utc_now
from app.auth.models import Organization
from app.content import storage
from app.db import get_sessionmaker
from app.tenancy.purge import purge_org_data
from app.tenancy.scoped import bind_org


def expired_org_ids(session: Session, now: datetime | None = None) -> list[str]:
    # organizations is the one shared table, so it is read directly.
    moment = now or utc_now()
    return list(
        session.scalars(
            select(Organization.id).where(
                Organization.kind == "sandbox",
                Organization.expires_at.is_not(None),
                Organization.expires_at <= moment,
            )
        )
    )


def delete_org(factory: sessionmaker, org_id: str) -> None:
    with factory() as session:
        bind_org(session, org_id)
        purge_org_data(session)
        org = session.get(Organization, org_id)
        if org is not None:
            session.delete(org)
        session.commit()
    # Uploads live in the org's own folder.
    shutil.rmtree(storage.stored_path(f"{org_id}/x").parent, ignore_errors=True)


def delete_expired(
    factory: sessionmaker | None = None, now: datetime | None = None
) -> list[str]:
    """Deletes every expired sandbox org. Returns the ids it deleted."""
    factory = factory or get_sessionmaker()
    with factory() as session:
        ids = expired_org_ids(session, now)
    for org_id in ids:
        delete_org(factory, org_id)
    return ids


def main() -> None:
    deleted = delete_expired()
    print(f"Deleted {len(deleted)} expired workspace(s).")


if __name__ == "__main__":
    main()
