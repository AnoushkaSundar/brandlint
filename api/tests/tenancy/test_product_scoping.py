"""Block 3: the product tables are per org, beyond what the route test checks.

The route test shows org B can't reach org A's rows. These show the other half: two orgs
can each hold the same ids, each org has its own rulebook version, and uploaded files are
kept apart.
"""

from __future__ import annotations

import pytest
from app import db
from app.admin import models as admin
from app.admin.rulebook import RulebookNotFound, current_rulebook_version, rulebook_at
from app.tenancy import bind_org
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.tenancy.world import make_org


def bound(org_id: str) -> Session:
    session = db.get_sessionmaker()()
    bind_org(session, org_id)
    return session


# The same id in two orgs


def rule(org_id: str, version: int = 1, status: str = "approved", rule_id: str = "R1"):
    return admin.Rule(
        org_id=org_id,
        id=rule_id,
        version=version,
        type="judgment",
        text="Be kind.",
        clause_ref="§1.1",
        severity="low",
        channel_scope=[],
        status=status,
    )


def test_two_orgs_can_each_have_rule_r1_version_1(world, database):
    with Session(database) as session:
        session.add_all([rule(world.a.org.id), rule(world.b.org.id)])
        session.commit()

        count = session.scalar(
            select(func.count()).select_from(admin.Rule).where(admin.Rule.id == "R1")
        )

    assert count == 2


def test_two_orgs_can_each_have_fact_f1_term_t1_and_asset_a1(world, database):
    with Session(database) as session:
        for org in (world.a, world.b):
            session.add(
                admin.Fact(
                    org_id=org.org.id,
                    id="F1",
                    version=1,
                    statement="s",
                    value="v",
                    source_doc="d",
                    owner="o",
                    valid_until=None,
                    data_class="public",
                )
            )
            session.add(
                admin.Term(org_id=org.org.id, id="T1", preferred="p", banned=[])
            )
            session.add(
                admin.Asset(
                    org_id=org.org.id, id="A1", kind="palette", file_ref="", meta={}
                )
            )
        session.commit()

        assert (
            session.scalar(
                select(func.count())
                .select_from(admin.Fact)
                .where(admin.Fact.id == "F1")
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(admin.Term)
                .where(admin.Term.id == "T1")
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(admin.Asset)
                .where(admin.Asset.id == "A1")
            )
            == 2
        )


def test_the_same_rule_id_twice_in_one_org_is_still_refused(world, database):
    from sqlalchemy.exc import IntegrityError

    with Session(database) as session:
        session.add_all([rule(world.a.org.id), rule(world.a.org.id)])
        with pytest.raises(IntegrityError):
            session.commit()


def test_each_org_numbers_its_own_facts(world, client_for):
    body = {
        "statement": "Customers rate us 4.5.",
        "value": "4.5",
        "source_doc": "Survey",
        "owner": "Insights",
        "valid_until": None,
        "data_class": "public",
    }

    first = client_for(world.a.admin).post("/admin/facts", json=body)
    second = client_for(world.b.admin).post("/admin/facts", json=body)

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] == second.json()["id"] == "F-001"


# The rulebook is per org


def test_approving_a_rule_in_org_a_does_not_bump_org_bs_rulebook_version(
    world, client_for
):
    a_draft = world.a.ids["rule_id"]
    with bound(world.b.org.id) as session:
        before = current_rulebook_version(session)
    with bound(world.a.org.id) as session:
        assert current_rulebook_version(session) == 1

    approved = client_for(world.a.admin).post(
        "/admin/rules/approve", json={"rule_ids": [a_draft]}
    )

    assert approved.status_code == 200
    assert approved.json() == {"version": 2}
    with bound(world.a.org.id) as session:
        assert current_rulebook_version(session) == 2
    with bound(world.b.org.id) as session:
        assert current_rulebook_version(session) == before == 1


def test_an_orgs_rulebook_holds_only_its_own_rules(world):
    with bound(world.a.org.id) as session:
        assert {r.id for r in rulebook_at(session)} == {world.a.ids["approved_rule_id"]}
    with bound(world.b.org.id) as session:
        assert {r.id for r in rulebook_at(session)} == {world.b.ids["approved_rule_id"]}


def test_a_new_org_has_no_rulebook_and_that_is_a_clear_error(world, database):
    with Session(database) as session:
        empty = make_org(session, "C")
        session.commit()

    with bound(empty.id) as session:
        assert current_rulebook_version(session) == 1
        with pytest.raises(RulebookNotFound):
            rulebook_at(session)


# The gap log


def a_gap(review_id: str) -> list[dict]:
    return [
        {
            "id": "gap-new-1",
            "review_id": review_id,
            "check": "tone",
            "text": "Too breezy",
            "explanation": "No rule covers this.",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]


def test_a_gap_is_logged_against_a_review_of_the_callers_org(world, client_for):
    response = client_for(world.a.admin).post(
        "/admin/gaps", json=a_gap(world.a.ids["review_id"])
    )

    assert response.status_code == 200
    assert response.json() == {"saved": 1}


def test_a_gap_for_another_orgs_review_is_refused_and_not_saved(world, client_for, database):
    from app.admin.models import Gap

    response = client_for(world.b.admin).post(
        "/admin/gaps", json=a_gap(world.a.ids["review_id"])
    )

    assert response.status_code == 404
    with Session(database) as session:
        assert session.get(Gap, "gap-new-1") is None


def test_a_gap_for_a_review_that_does_not_exist_gets_the_same_answer(world, client_for):
    other = client_for(world.b.admin).post("/admin/gaps", json=a_gap(world.a.ids["review_id"]))
    missing = client_for(world.b.admin).post("/admin/gaps", json=a_gap("eng-nowhere"))

    assert (other.status_code, other.json()) == (missing.status_code, missing.json())


# Uploaded files


def upload_as(client, name="draft.txt", data=b"Hello there."):
    return client.post(
        "/content",
        data={
            "title": "Upload",
            "channel": "blog",
            "source": "in-house",
            "data_class": "public",
        },
        files={"file": (name, data)},
    )


def test_a_new_row_is_put_in_the_creators_org(world, client_for, database):
    created = upload_as(client_for(world.a.creator)).json()

    with Session(database) as session:
        content = session.get(
            __import__("app.content.models", fromlist=["Content"]).Content,
            created["id"],
        )
    assert str(content.org_id) == world.a.org.id


def test_an_upload_is_stored_under_its_orgs_folder(world, client_for, database):
    from app.content.models import ContentVersion

    created = upload_as(client_for(world.a.creator)).json()
    version_id = created["versions"][0]["id"]

    with Session(database) as session:
        file_ref = session.get(ContentVersion, version_id).file_ref
    assert file_ref.startswith(f"{world.a.org.id}/")


def test_a_file_is_served_to_its_own_org_and_to_nobody_else(world, client_for):
    created = upload_as(client_for(world.a.creator)).json()
    path = f"/content/versions/{created['versions'][0]['id']}/file"

    assert client_for(world.a.admin).get(path).content == b"Hello there."
    assert client_for(world.b.admin).get(path).status_code == 404
    assert client_for(world.b.reviewer).get(path).status_code == 404
