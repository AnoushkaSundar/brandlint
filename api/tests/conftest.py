"""Test setup shared by every test.

Some tests were written before organisations existed. They build their own database with
`Base.metadata.create_all` and add users without saying which org they are in. So that
they keep exercising what they were written for, the files listed in LEGACY_FILES get two
things, and only they do:

- every database built with `create_all` gets the Tarnhollow demo org, and
- every session starts bound to it, so a row added without an org goes into it and a query
  made without one is for it.

Nothing in the app does either, and no other test does: a test that forgets to name an
org fails, which is the point. That includes everything under tests/tenancy/, where a
default org could hide a leak between orgs. Don't add a file to LEGACY_FILES. Give its
users an org instead, and remove the file from the list.
"""

import pytest
from app.auth.models import Organization, User
from app.auth.orgs import DEMO_NAME, DEMO_ORG_ID, DEMO_SLUG
from app.db import Base
from sqlalchemy import event, insert
from sqlalchemy.orm import Session

# The tests that relied on this when it was added. The list only shrinks.
LEGACY_FILES = frozenset(
    {
        "test_admin.py",
        "test_auth.py",
        "test_content.py",
        "test_governance.py",
        "test_insights.py",
        "test_memory.py",
        "test_review_access.py",
        "test_review_desk.py",
        "test_workflow.py",
        # Engine and gateway tests that open their own sessions. Block 4 gives them an org.
        "test_cache_replay.py",
        "test_fixer.py",
        "test_disclosure.py",
        "test_findings_stream.py",
        "test_gateway.py",
        "test_masking.py",
        "test_unreadable_files.py",
    }
)

_legacy_test_running = False


@pytest.fixture(autouse=True)
def _never_migrate_a_real_database(monkeypatch):
    """Migrations pick MIGRATION_DATABASE_URL over the app's own URL, as production needs.
    A test that runs migrations on a temporary database must never be redirected to a real
    one, so the tests ignore the variable unless one of them sets it itself."""
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)


@pytest.fixture(autouse=True)
def _legacy_org_defaults(request):
    global _legacy_test_running
    path = request.node.path
    _legacy_test_running = path.name in LEGACY_FILES and "tenancy" not in path.parts
    yield
    _legacy_test_running = False


@event.listens_for(Base.metadata, "after_create")
def _add_the_demo_org(target, connection, tables=None, **kwargs):
    if not _legacy_test_running:
        return
    if tables is not None and Organization.__table__ not in tables:
        return
    connection.execute(
        insert(Organization.__table__).values(
            id=DEMO_ORG_ID, name=DEMO_NAME, slug=DEMO_SLUG, kind="demo", status="active"
        )
    )


@event.listens_for(User, "before_insert")
def _default_to_the_demo_org(mapper, connection, user):
    if _legacy_test_running and user.org_id is None:
        user.org_id = DEMO_ORG_ID


_session_init = Session.__init__


def _bind_the_demo_org(self, *args, **kwargs):
    """Sessions made during a legacy test start bound to the demo org."""
    _session_init(self, *args, **kwargs)
    if _legacy_test_running:
        self.info.setdefault("org_id", DEMO_ORG_ID)


Session.__init__ = _bind_the_demo_org
