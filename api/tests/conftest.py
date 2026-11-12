"""Test setup shared by every test.

Some tests were written before organisations existed. They build their own database with
`Base.metadata.create_all` and add users without saying which org they are in. So that
they keep exercising what they were written for, the files listed in LEGACY_FILES get two
things, and only they do:

- every database built with `create_all` gets the Tarnhollow demo org, and
- a user added through the ORM without an org goes into it.

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
    }
)

_legacy_test_running = False


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
