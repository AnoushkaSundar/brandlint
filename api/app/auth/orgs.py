"""Organisations: the demo workspace, and who may use a workspace right now."""

from datetime import datetime
from enum import Enum

from sqlalchemy.orm import Session

from app.auth.defaults import utc_now
from app.auth.models import Organization

# Fixed, so the migration, the seed and the tests all mean the same organisation.
# The migration repeats this value, and a test keeps the two equal.
DEMO_ORG_ID = "00000000-0000-4000-8000-000000000001"
DEMO_NAME = "Tarnhollow"
DEMO_SLUG = "tarnhollow"


class OrgKind(str, Enum):
    demo = "demo"
    sandbox = "sandbox"


class OrgStatus(str, Enum):
    active = "active"
    suspended = "suspended"


def ensure_demo_org(session: Session) -> Organization:
    """Returns the Tarnhollow demo org, creating it if it isn't there. The caller commits."""
    org = session.get(Organization, DEMO_ORG_ID)
    if org is None:
        org = Organization(
            id=DEMO_ORG_ID,
            name=DEMO_NAME,
            slug=DEMO_SLUG,
            kind=OrgKind.demo.value,
            status=OrgStatus.active.value,
        )
        session.add(org)
        session.flush()
    return org


def inactive_reason(
    org: Organization | None, now: datetime | None = None
) -> str | None:
    """Why nobody in this org can sign in, or None when they can."""
    if org is None:
        return "This workspace isn't available."
    if org.status != OrgStatus.active.value:
        return "This workspace is suspended."
    expires = org.expires_at
    if expires is not None:
        if expires.tzinfo is None:
            # SQLite hands back naive datetimes. They are stored as UTC.
            expires = expires.replace(tzinfo=utc_now().tzinfo)
        if expires <= (now or utc_now()):
            return "This workspace has expired."
    return None
