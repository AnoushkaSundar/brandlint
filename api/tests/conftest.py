"""Test setup shared by every test.

Most tests were written before organisations existed. They build their own database
with `Base.metadata.create_all` and add users without saying which org they are in. So
that they keep exercising what they were written for, two things happen here, for tests
only:

- every database built with `create_all` gets the Tarnhollow demo org, and
- a user added through the ORM without an org goes into it.

Nothing in the app does either. The app always names the org, and a test that checks the
rule itself goes through the table (see test_a_user_must_belong_to_an_org). The tenancy
tests name their orgs explicitly, so this never hides a mistake there.
"""

from app.auth.models import Organization, User
from app.auth.orgs import DEMO_NAME, DEMO_ORG_ID, DEMO_SLUG
from app.db import Base
from sqlalchemy import event, insert


@event.listens_for(Base.metadata, "after_create")
def _add_the_demo_org(target, connection, tables=None, **kwargs):
    if tables is not None and Organization.__table__ not in tables:
        return
    connection.execute(
        insert(Organization.__table__).values(
            id=DEMO_ORG_ID, name=DEMO_NAME, slug=DEMO_SLUG, kind="demo", status="active"
        )
    )


@event.listens_for(User, "before_insert")
def _default_to_the_demo_org(mapper, connection, user):
    if user.org_id is None:
        user.org_id = DEMO_ORG_ID
