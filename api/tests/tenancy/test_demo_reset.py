"""Block 6: resetting the demo touches only the demo org, and a new org starts empty."""

from __future__ import annotations

from app import db
from app.admin import models as admin
from app.admin.demo import reset_demo
from app.auth.models import User
from app.auth.orgs import DEMO_ORG_ID, ensure_demo_org
from app.auth.seed import seed_users
from app.content.models import Content, ContentVersion
from app.tenancy import bind_org, scoped
from tests.tenancy.state import problems, snapshot
from tests.tenancy.world import Org, _person, make_org


def _demo_org_with_a_piece() -> None:
    with db.get_sessionmaker()() as session:
        ensure_demo_org(session)
        bind_org(session, DEMO_ORG_ID)
        seed_users(session)
        creator = session.scalars(scoped(session, User)).first()
        session.add(
            Content(
                id="demo-piece",
                title="Demo draft",
                channel="blog",
                source="in-house",
                data_class="public",
                state="draft",
                creator_id=creator.id,
            )
        )
        session.commit()


def test_reset_in_the_demo_org_leaves_every_other_org_untouched(world):
    _demo_org_with_a_piece()
    owned = world.a.owned_ids | world.b.owned_ids
    before = snapshot(db.get_engine())

    with db.get_sessionmaker()() as session:
        bind_org(session, DEMO_ORG_ID)
        reset_demo(session)

    after = snapshot(db.get_engine())
    assert problems(before, after, owned) == []
    with db.get_sessionmaker()() as session:
        bind_org(session, DEMO_ORG_ID)
        assert session.get(Content, "demo-piece") is None
        assert session.scalars(scoped(session, admin.Rule)).first() is not None


def test_another_org_cannot_reset_the_demo(world, client_for):
    before = snapshot(db.get_engine())
    response = client_for(world.a.admin).post("/admin/demo/reset")
    assert response.status_code == 403
    assert snapshot(db.get_engine()) == before


def test_a_review_in_an_empty_org_is_blocked_with_a_reason(database, client_for):
    with db.get_sessionmaker()() as session:
        org: Org = make_org(session, "Empty")
        creator = _person(session, org, "Empty", "creator")
        session.add(
            Content(
                id="c-empty",
                title="Draft",
                channel="blog",
                source="in-house",
                data_class="public",
                state="draft",
                creator_id=creator.id,
                org_id=org.id,
            )
        )
        session.flush()
        session.add(
            ContentVersion(
                id="v-empty",
                content_id="c-empty",
                version=1,
                text="Hello.",
                created_by=creator.id,
                org_id=org.id,
            )
        )
        session.commit()
    response = client_for(creator).post("/content/c-empty/reviews")
    assert response.status_code == 409
    assert "no approved rules" in response.json()["detail"]
