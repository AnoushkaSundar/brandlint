"""The read-only brand data the engine depends on, and the gap log.

The API tests call the routes directly, because the UI hiding a fact proves nothing.
"""

from datetime import UTC, date, datetime

import app.content.models
import app.governance.models
import app.workflow.models
import pytest
from app.admin.brand import list_facts, list_terms, visible_facts
from app.admin.gaps import save_gaps
from app.admin.models import Fact as FactRow
from app.admin.models import Gap as GapRow
from app.admin.models import Rule as RuleRow
from app.admin.router import router as admin_router
from app.admin.rulebook import RulebookNotFound, rulebook_at
from app.admin.seed import seed_brand
from app.auth.models import User
from app.auth.router import router as auth_router
from app.auth.security import SESSION_COOKIE, create_token, hash_password
from app.contracts import CheckType, DataClass, Gap, Role, RuleStatus
from app.db import Base, get_session
from app.workflow.models import AuditLog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

CODENAME = "Bluewren"
READERS = [Role.admin, Role.legal]
NON_READERS = [Role.creator, Role.reviewer, Role.manager]


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "a-test-only-secret-that-is-long-enough-for-hs256")


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        yield db


@pytest.fixture
def seeded(session):
    seed_brand(session)
    return session


@pytest.fixture
def client_for(session):
    api = FastAPI()
    api.include_router(auth_router)
    api.include_router(admin_router)

    def override_session():
        yield session

    api.dependency_overrides[get_session] = override_session

    def build(role=None):
        client = TestClient(api)
        if role is not None:
            user = User(
                email=f"{role.value}@example.com",
                name=role.value,
                role=role.value,
                password_hash=hash_password("not-used-here"),
            )
            session.add(user)
            session.commit()
            client.cookies.set(SESSION_COOKIE, create_token(user))
        return client

    return build


def rule_row(rule_id, version, status, **fields):
    return RuleRow(
        id=rule_id,
        version=version,
        type="judgment",
        text=f"{rule_id} at version {version}",
        clause_ref="§9.9",
        severity="low",
        channel_scope=["all"],
        status=status.value,
        **fields,
    )


def ids(rules):
    return [rule.id for rule in rules]


def make_gap(gap_id="gap:rev-1:tone:abc", text="No rule covers this"):
    return Gap(
        id=gap_id,
        review_id="rev-1",
        check=CheckType.tone,
        text=text,
        explanation="The critic found no source.",
        created_at=datetime(2026, 11, 6, 12, tzinfo=UTC),
    )


# Seeding


def test_seed_loads_the_demo_brand(session):
    assert seed_brand(session) == {"rules": 19, "facts": 10, "terms": 4, "assets": 3}


def test_seed_twice_adds_nothing(seeded):
    assert seed_brand(seeded) == {"rules": 0, "facts": 0, "terms": 0, "assets": 0}


def test_seed_keeps_an_admins_edit(seeded):
    fact = seeded.get(FactRow, ("F-001", 1))
    fact.owner = "Someone who took this over"
    seeded.commit()

    seed_brand(seeded)

    assert seeded.get(FactRow, ("F-001", 1)).owner == "Someone who took this over"


def test_seed_stores_expiry_dates_as_dates(seeded):
    assert seeded.get(FactRow, ("F-003", 1)).valid_until == date(2026, 3, 31)
    assert seeded.get(FactRow, ("F-009", 1)).valid_until is None


# The rulebook


def test_the_rulebook_leaves_out_the_draft_rule(seeded):
    rules = rulebook_at(seeded)

    assert len(rules) == 18
    assert "R-TERM-04" not in ids(rules)
    assert all(rule.status == RuleStatus.approved for rule in rules)


def test_the_rulebook_carries_the_required_text(seeded):
    rules = {rule.id: rule for rule in rulebook_at(seeded)}

    assert rules["R-REQ-01"].required_text == "Results vary by organisation."
    assert rules["R-TERM-01"].required_text is None


def test_a_review_pinned_to_an_old_version_keeps_the_old_wording(session, monkeypatch):
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda *args: 2)
    session.add_all(
        [
            rule_row("R-1", 1, RuleStatus.approved),
            rule_row("R-1", 2, RuleStatus.approved),
        ]
    )
    session.commit()

    assert rulebook_at(session, 1)[0].text == "R-1 at version 1"
    assert rulebook_at(session, 2)[0].text == "R-1 at version 2"
    assert rulebook_at(session)[0].version == 2


def test_a_draft_edit_does_not_replace_the_approved_rule(session, monkeypatch):
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda *args: 2)
    session.add_all(
        [rule_row("R-1", 1, RuleStatus.approved), rule_row("R-1", 2, RuleStatus.draft)]
    )
    session.commit()

    assert rulebook_at(session)[0].version == 1


def test_a_retired_rule_stays_in_older_versions_only(session, monkeypatch):
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda *args: 2)
    session.add_all(
        [
            rule_row("R-1", 1, RuleStatus.approved),
            rule_row("R-1", 2, RuleStatus.retired),
            rule_row("R-2", 1, RuleStatus.approved),
        ]
    )
    session.commit()

    assert ids(rulebook_at(session, 1)) == ["R-1", "R-2"]
    assert ids(rulebook_at(session, 2)) == ["R-2"]


def test_a_superseded_rule_gives_way_to_its_replacement(session, monkeypatch):
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda *args: 2)
    session.add_all(
        [
            rule_row("R-1", 1, RuleStatus.approved),
            rule_row("R-2", 2, RuleStatus.approved, supersedes="R-1"),
        ]
    )
    session.commit()

    assert ids(rulebook_at(session, 1)) == ["R-1"]
    assert ids(rulebook_at(session, 2)) == ["R-2"]


def test_a_rule_superseding_its_own_old_version_stays_in_force(session, monkeypatch):
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda *args: 2)
    session.add_all(
        [
            rule_row("R-1", 1, RuleStatus.approved),
            rule_row("R-1", 2, RuleStatus.approved, supersedes="R-1"),
        ]
    )
    session.commit()

    assert rulebook_at(session)[0].version == 2


def test_a_future_version_is_refused(seeded):
    with pytest.raises(RulebookNotFound):
        rulebook_at(seeded, 2)


def test_an_empty_rulebook_is_refused_so_nothing_passes_by_accident(session):
    with pytest.raises(RulebookNotFound):
        rulebook_at(session)


# Facts and terms


def test_the_engine_gets_every_fact_including_expired_and_protected(seeded):
    facts = {fact.id: fact for fact in list_facts(seeded)}

    assert len(facts) == 10
    assert facts["F-003"].valid_until == date(2026, 3, 31)
    assert facts["F-010"].data_class == DataClass.confidential


def test_only_the_newest_version_of_a_fact_is_returned(seeded):
    old = seeded.get(FactRow, ("F-001", 1))
    seeded.add(
        FactRow(
            id="F-001",
            version=2,
            statement="A corrected statement.",
            value=old.value,
            source_doc=old.source_doc,
            owner=old.owner,
            data_class=old.data_class,
        )
    )
    seeded.commit()

    facts = {fact.id: fact for fact in list_facts(seeded)}

    assert len(facts) == 10
    assert facts["F-001"].statement == "A corrected statement."


def test_terms_keep_their_governing_rule(seeded):
    terms = {term.id: term for term in list_terms(seeded)}

    assert terms["T-001"].rule_id == "R-TERM-02"
    assert terms["T-001"].rule_version == 1
    assert terms["T-004"].rule_id is None


@pytest.mark.parametrize("role", NON_READERS)
def test_visible_facts_hides_protected_classes(seeded, role):
    restricted = list_facts(seeded)[0].model_copy(
        update={"id": "F-999", "data_class": DataClass.restricted}
    )

    visible = visible_facts([*list_facts(seeded), restricted], role.value)

    assert {fact.data_class for fact in visible} == {
        DataClass.public,
        DataClass.internal,
    }


# The API


@pytest.mark.parametrize(
    "path", ["/admin/rulebook", "/admin/facts", "/admin/terms", "/admin/assets"]
)
def test_brand_data_needs_a_signed_in_user(client_for, path):
    assert client_for().get(path).status_code == 401


@pytest.mark.parametrize("role", NON_READERS)
def test_the_api_keeps_the_codename_from_these_roles(seeded, client_for, role):
    client = client_for(role)

    response = client.get("/admin/facts")

    assert response.status_code == 200
    assert len(response.json()) == 9
    assert "F-010" not in {fact["id"] for fact in response.json()}
    assert CODENAME not in response.text


@pytest.mark.parametrize("role", READERS)
def test_admin_and_legal_can_read_the_protected_fact(seeded, client_for, role):
    response = client_for(role).get("/admin/facts")

    assert len(response.json()) == 10
    assert CODENAME in response.text


@pytest.mark.parametrize("path", ["/admin/rulebook", "/admin/terms", "/admin/assets"])
def test_no_other_brand_route_carries_the_codename(seeded, client_for, path):
    response = client_for(Role.creator).get(path)

    assert response.status_code == 200
    assert response.json()
    assert CODENAME not in response.text


def test_the_rulebook_route_matches_the_contract(seeded, client_for):
    body = client_for(Role.creator).get("/admin/rulebook", params={"version": 1}).json()

    assert len(body) == 18
    assert {rule["version"] for rule in body} == {1}


@pytest.mark.parametrize(
    ("version", "status"), [("2", 404), ("0", 422), ("latest", 422)]
)
def test_the_rulebook_route_refuses_bad_versions(seeded, client_for, version, status):
    response = client_for(Role.creator).get(
        "/admin/rulebook", params={"version": version}
    )

    assert response.status_code == status


# The gap log


def test_saving_a_gap_stores_every_field(session):
    assert save_gaps(session, [make_gap()]) == 1
    session.commit()

    row = session.scalars(select(GapRow)).one()
    assert row.id == "gap:rev-1:tone:abc"
    assert row.review_id == "rev-1"
    assert row.check == "tone"
    assert row.text == "No rule covers this"
    assert row.explanation == "The critic found no source."


def test_a_repeated_gap_is_kept_once_and_not_overwritten(session):
    save_gaps(session, [make_gap(text="The first wording")])
    session.commit()

    assert save_gaps(session, [make_gap(text="A later wording")]) == 0
    session.commit()

    assert session.scalars(select(GapRow)).one().text == "The first wording"


def test_a_gap_repeated_within_one_batch_is_kept_once(session):
    assert save_gaps(session, [make_gap(), make_gap()]) == 1


def test_no_gaps_is_fine(session):
    assert save_gaps(session, []) == 0


def test_the_gap_id_column_fits_the_longest_engine_id():
    """SQLite ignores column lengths, so this would otherwise first fail on Postgres."""
    review_id = "0" * 36
    longest = f"gap:{review_id}:{CheckType.required_element.value}:{'a' * 12}"

    assert len(longest) <= GapRow.__table__.c.id.type.length


def test_an_admin_can_post_gaps_and_they_are_committed(session, client_for):
    client = client_for(Role.admin)

    response = client.post("/admin/gaps", json=[make_gap().model_dump(mode="json")])
    session.rollback()

    assert response.status_code == 200
    assert response.json() == {"saved": 1}
    assert session.scalars(select(GapRow)).one().check == "tone"


@pytest.mark.parametrize("role", NON_READERS + [Role.legal])
def test_other_roles_cannot_post_gaps(session, client_for, role):
    response = client_for(role).post(
        "/admin/gaps", json=[make_gap().model_dump(mode="json")]
    )

    assert response.status_code == 403
    assert session.scalars(select(GapRow)).first() is None


def test_a_malformed_gap_is_refused(client_for):
    response = client_for(Role.admin).post("/admin/gaps", json=[{"id": "gap-1"}])

    assert response.status_code == 422


# Editing brand data


NEW_FACT = {
    "statement": "Customers cut onboarding time by 41% on average.",
    "value": "41%",
    "source_doc": "Customer study 2026",
    "owner": "Insights team",
    "valid_until": "2027-12-31",
    "data_class": "public",
}


@pytest.fixture
def no_impact(monkeypatch):
    monkeypatch.setattr("app.admin.router.memory.impact", lambda fact_id, session: [])


def test_editing_a_fact_adds_a_version_and_keeps_the_old_one(
    seeded, client_for, no_impact
):
    response = client_for(Role.admin).put("/admin/facts/F-002", json=NEW_FACT)

    assert response.status_code == 200
    assert response.json()["fact"]["version"] == 2
    assert response.json()["impact"] == []
    assert seeded.get(FactRow, ("F-002", 1)).value != "41%"
    assert {fact.id: fact for fact in list_facts(seeded)}["F-002"].value == "41%"


def test_a_fact_edit_reports_the_affected_pieces(seeded, client_for, monkeypatch):
    affected = [{"content_id": "c1", "state": "published", "claim_text": "by 80%"}]
    monkeypatch.setattr(
        "app.admin.router.memory.impact", lambda fact_id, session: affected
    )

    response = client_for(Role.admin).put("/admin/facts/F-002", json=NEW_FACT)

    assert response.json()["impact"] == affected


def test_a_fact_edit_is_audited_with_before_and_after(seeded, client_for, no_impact):
    client_for(Role.admin).put("/admin/facts/F-002", json=NEW_FACT)

    entry = seeded.scalars(select(AuditLog).where(AuditLog.action == "fact:edit")).one()
    assert entry.target_id == "F-002"
    assert entry.before["version"] == 1
    assert entry.after["value"] == "41%"


def test_an_unchanged_fact_is_refused(seeded, client_for, no_impact):
    current = {fact.id: fact for fact in list_facts(seeded)}["F-001"].model_dump(
        mode="json"
    )
    body = {key: current[key] for key in NEW_FACT}

    assert (
        client_for(Role.admin).put("/admin/facts/F-001", json=body).status_code == 409
    )


@pytest.mark.parametrize("role", NON_READERS + [Role.legal])
def test_only_an_admin_edits_brand_data(seeded, client_for, role):
    client = client_for(role)

    assert client.put("/admin/facts/F-002", json=NEW_FACT).status_code == 403
    assert client.post("/admin/facts", json=NEW_FACT).status_code == 403
    assert client.post("/admin/terms", json={"preferred": "x"}).status_code == 403


def test_a_new_fact_gets_the_next_id(seeded, client_for):
    response = client_for(Role.admin).post("/admin/facts", json=NEW_FACT)

    assert response.status_code == 201
    assert response.json()["id"] == "F-011"


def test_a_bad_fact_is_refused(seeded, client_for):
    assert (
        client_for(Role.admin)
        .post("/admin/facts", json={**NEW_FACT, "value": ""})
        .status_code
        == 422
    )


def test_terms_can_be_added_and_edited(seeded, client_for):
    admin = client_for(Role.admin)

    created = admin.post(
        "/admin/terms", json={"preferred": "teammate", "banned": [" staffer ", ""]}
    )
    assert created.json()["banned"] == ["staffer"]

    edited = admin.put(
        f"/admin/terms/{created.json()['id']}",
        json={
            "preferred": "teammate",
            "banned": ["staffer", "worker"],
            "rule_id": "R-TERM-03",
        },
    )
    assert edited.json()["banned"] == ["staffer", "worker"]
    assert edited.json()["rule_id"] == "R-TERM-03"


def test_a_palette_needs_real_colours(seeded, client_for):
    admin = client_for(Role.admin)

    assert admin.post("/admin/assets/palette", json={"colours": ["#12343b"]}).json()[
        "meta"
    ] == {"colours": ["#12343B"]}
    assert (
        admin.post("/admin/assets/palette", json={"colours": ["teal"]}).status_code
        == 422
    )


def test_a_logo_upload_is_stored_and_listed(seeded, client_for, tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    admin = client_for(Role.admin)

    response = admin.post(
        "/admin/assets",
        data={"kind": "logo"},
        files={"file": ("logo.png", b"\x89PNG\r\n\x1a\n data")},
    )

    assert response.status_code == 201
    stored = tmp_path / response.json()["file_ref"]
    assert stored.read_bytes().startswith(b"\x89PNG")
    assert response.json()["id"] in {
        asset["id"] for asset in admin.get("/admin/assets").json()
    }


@pytest.mark.parametrize(
    ("name", "data"),
    [("logo.svg", b"<svg/>"), ("logo.png", b"not a png"), ("guide.pdf", b"%PDF-1.7")],
)
def test_only_png_or_jpeg_assets_are_accepted(
    seeded, client_for, tmp_path, monkeypatch, name, data
):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

    response = client_for(Role.admin).post(
        "/admin/assets", data={"kind": "logo"}, files={"file": (name, data)}
    )

    assert response.status_code == 422


def test_the_rulebook_version_follows_approved_rules(seeded):
    from app.admin.rulebook import current_rulebook_version

    assert current_rulebook_version(seeded) == 1
    seeded.add(rule_row("R-NEW", 2, RuleStatus.approved))
    seeded.commit()

    assert current_rulebook_version(seeded) == 2


# Ingest and approval


@pytest.fixture
def guideline():
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[2] / "demo" / "brand" / "guidelines.pdf"
    ).read_bytes()


@pytest.fixture
def empty_rulebook(session):
    seed_brand(session, rules=False)
    return session


def upload(client, data, name="guidelines.pdf"):
    return client.post("/admin/ingest", files={"file": (name, data)})


def test_a_guideline_becomes_drafts_with_its_conflict_flagged(
    empty_rulebook, client_for, guideline
):
    admin = client_for(Role.admin)

    response = upload(admin, guideline)

    assert response.status_code == 201
    assert response.json()["status"] == "done"
    listing = admin.get("/admin/rules/drafts").json()
    assert listing["version"] == 1
    assert len(listing["drafts"]) == 19
    assert sorted(listing["conflicts"][0]) == ["R-TERM-04", "R-TONE-04"]


def test_ingest_keeps_required_text(empty_rulebook, client_for, guideline):
    admin = client_for(Role.admin)
    upload(admin, guideline)

    drafts = {
        rule["id"]: rule for rule in admin.get("/admin/rules/drafts").json()["drafts"]
    }

    assert drafts["R-REQ-01"]["required_text"] == "Results vary by organisation."


def test_nothing_is_live_until_an_admin_approves(empty_rulebook, client_for, guideline):
    upload(client_for(Role.admin), guideline)

    with pytest.raises(RulebookNotFound):
        rulebook_at(empty_rulebook)


def test_both_sides_of_a_conflict_cant_be_approved(
    empty_rulebook, client_for, guideline
):
    admin = client_for(Role.admin)
    upload(admin, guideline)
    ids = [rule["id"] for rule in admin.get("/admin/rules/drafts").json()["drafts"]]

    response = admin.post("/admin/rules/approve", json={"rule_ids": ids})

    assert response.status_code == 409
    assert "contradict" in response.json()["detail"]


def test_rejecting_one_side_lets_the_rulebook_go_live(
    empty_rulebook, client_for, guideline
):
    admin = client_for(Role.admin)
    upload(admin, guideline)
    assert admin.delete("/admin/rules/R-TERM-04/draft").status_code == 204
    ids = [rule["id"] for rule in admin.get("/admin/rules/drafts").json()["drafts"]]

    response = admin.post("/admin/rules/approve", json={"rule_ids": ids})

    assert response.json() == {"version": 1}
    assert len(rulebook_at(empty_rulebook)) == 18
    assert admin.get("/admin/rules/drafts").json()["drafts"] == []


def test_an_approved_rule_is_no_longer_a_draft(empty_rulebook, client_for, guideline):
    admin = client_for(Role.admin)
    upload(admin, guideline)
    admin.delete("/admin/rules/R-TERM-04/draft")
    ids = [rule["id"] for rule in admin.get("/admin/rules/drafts").json()["drafts"]]
    admin.post("/admin/rules/approve", json={"rule_ids": ids})

    admin.put(
        "/admin/rules/R-TONE-01/draft",
        json={"text": "x", "severity": "low", "channel_scope": []},
    )
    assert (
        admin.post("/admin/rules/approve", json={"rule_ids": ["R-TONE-01"]}).status_code
        == 404
    )


def test_an_unchanged_rule_is_not_drafted_again(seeded, client_for, guideline):
    admin = client_for(Role.admin)

    upload(admin, guideline)

    drafts = admin.get("/admin/rules/drafts").json()["drafts"]
    assert [rule["id"] for rule in drafts] == ["R-TERM-04"]


def test_a_draft_can_be_edited_before_approval(empty_rulebook, client_for, guideline):
    admin = client_for(Role.admin)
    upload(admin, guideline)

    response = admin.put(
        "/admin/rules/R-TONE-01/draft",
        json={"text": "Write warmly.", "severity": "low", "channel_scope": ["blog"]},
    )

    assert response.json()["text"] == "Write warmly."
    assert response.json()["status"] == "draft"


def test_a_failed_model_reply_marks_the_job_failed(
    empty_rulebook, client_for, guideline, monkeypatch
):
    monkeypatch.setattr("app.admin.ingest.llm_call", lambda *a, **k: {"rules": "nope"})

    response = upload(client_for(Role.admin), guideline)

    assert response.json()["status"] == "failed"
    assert "wasn't usable" in response.json()["error"]


@pytest.mark.parametrize(
    ("name", "data"), [("guide.png", b"\x89PNG"), ("guide.txt", b"   ")]
)
def test_an_unusable_file_is_refused(empty_rulebook, client_for, name, data):
    assert upload(client_for(Role.admin), data, name).status_code == 422


@pytest.mark.parametrize("role", NON_READERS + [Role.legal])
def test_only_an_admin_ingests_or_approves(empty_rulebook, client_for, guideline, role):
    client = client_for(role)

    assert upload(client, guideline).status_code == 403
    assert (
        client.post(
            "/admin/rules/approve", json={"rule_ids": ["R-TONE-01"]}
        ).status_code
        == 403
    )
    assert client.get("/admin/rules/drafts").status_code == 403


def test_approval_is_audited(empty_rulebook, client_for, guideline):
    admin = client_for(Role.admin)
    upload(admin, guideline)
    admin.delete("/admin/rules/R-TERM-04/draft")
    ids = [rule["id"] for rule in admin.get("/admin/rules/drafts").json()["drafts"]]
    admin.post("/admin/rules/approve", json={"rule_ids": ids})

    actions = set(empty_rulebook.scalars(select(AuditLog.action)))

    assert {"rules:ingest", "rule:reject", "rules:approve"} <= actions


# Re-review after a fact changes


@pytest.fixture
def affected_piece(seeded, client_for, monkeypatch):
    from app.content.models import Content

    creator = User(
        email="writer@example.com",
        name="writer",
        role=Role.creator.value,
        password_hash="not-used",
    )
    seeded.add(creator)
    seeded.flush()
    content = Content(
        title="Launch post",
        channel="blog",
        source="in-house",
        data_class="public",
        creator_id=creator.id,
    )
    seeded.add(content)
    seeded.commit()
    monkeypatch.setattr(
        "app.admin.router.memory.impact",
        lambda fact_id, session: [
            {"content_id": content.id, "state": "draft", "claim_text": "by 30%"}
        ],
    )
    return content.id


def test_an_admin_queues_a_rereview(affected_piece, client_for, seeded):
    from app.content import rereview

    response = client_for(Role.admin).post(
        "/admin/facts/F-002/rereview", json={"content_ids": [affected_piece]}
    )

    assert response.json() == {"queued": [affected_piece]}
    request = rereview.pending(seeded, affected_piece, None)
    assert request is not None
    assert request.fact_id == "F-002"


def test_only_affected_pieces_can_be_queued(affected_piece, client_for):
    response = client_for(Role.admin).post(
        "/admin/facts/F-002/rereview", json={"content_ids": ["someone-else"]}
    )

    assert response.status_code == 422


@pytest.mark.parametrize("role", NON_READERS + [Role.legal])
def test_only_an_admin_queues_a_rereview(affected_piece, client_for, role):
    response = client_for(role).post(
        "/admin/facts/F-002/rereview", json={"content_ids": [affected_piece]}
    )

    assert response.status_code == 403


def test_a_request_is_audited(affected_piece, client_for, seeded):
    client_for(Role.admin).post(
        "/admin/facts/F-002/rereview", json={"content_ids": [affected_piece]}
    )

    entry = seeded.scalars(
        select(AuditLog).where(AuditLog.action == "content:rereview_requested")
    ).one()
    assert entry.target_id == affected_piece
    assert entry.after == {"fact_id": "F-002"}



# Approved proposals


def test_an_approved_proposal_becomes_a_draft_not_a_rule(seeded):
    from app.admin.ingest import draft_from_proposal

    admin = User(
        email="owner@example.com", name="owner", role=Role.admin.value, password_hash="x"
    )
    seeded.add(admin)
    seeded.flush()
    before = {rule.id: rule.text for rule in rulebook_at(seeded)}

    assert draft_from_proposal(seeded, "R-TONE-02", "Stay calm. Facts are fine.", admin) == "R-TONE-02"
    seeded.commit()

    assert {rule.id: rule.text for rule in rulebook_at(seeded)} == before
    draft = seeded.scalars(
        select(RuleRow).where(RuleRow.id == "R-TONE-02", RuleRow.status == "draft")
    ).one()
    assert draft.text == "Stay calm. Facts are fine."
    assert draft.version == 2


def test_a_proposal_for_a_retired_rule_makes_no_draft(seeded):
    from app.admin.ingest import draft_from_proposal

    admin = User(
        email="owner@example.com", name="owner", role=Role.admin.value, password_hash="x"
    )
    seeded.add(admin)
    seeded.flush()

    assert draft_from_proposal(seeded, "R-GONE", "Anything", admin) is None


def proposal_client(session, role):
    from app.governance.router import _routes

    api = FastAPI()
    api.include_router(_routes(), prefix="/governance")

    def override_session():
        yield session

    api.dependency_overrides[get_session] = override_session
    user = User(
        email=f"g-{role.value}@example.com",
        name=role.value,
        role=role.value,
        password_hash="x",
    )
    session.add(user)
    session.add(
        app.governance.models.Proposal(
            id="p1",
            rule_id="R-TONE-02",
            kind="amendment",
            current="Stay calm.",
            suggested="Stay calm. Facts are fine.",
            evidence={"count": 3, "examples": []},
            eval={"passed": True, "precision": 0.9, "recall": 0.9},
            status="pending",
        )
    )
    session.commit()
    client = TestClient(api)
    client.cookies.set(SESSION_COOKIE, create_token(user))
    return client


def test_an_admin_lists_and_approves_a_proposal_into_a_draft(seeded):
    client = proposal_client(seeded, Role.admin)

    assert [p["id"] for p in client.get("/governance/proposals").json()] == ["p1"]
    response = client.post("/governance/proposals/p1", json={"status": "approved"})

    assert response.json() == []
    draft = seeded.scalars(
        select(RuleRow).where(RuleRow.id == "R-TONE-02", RuleRow.status == "draft")
    ).one()
    assert draft.text == "Stay calm. Facts are fine."


def test_a_rejected_proposal_makes_no_draft(seeded):
    client = proposal_client(seeded, Role.admin)

    client.post("/governance/proposals/p1", json={"status": "rejected"})

    drafts = select(RuleRow).where(RuleRow.id == "R-TONE-02", RuleRow.status == "draft")
    assert seeded.scalars(drafts).all() == []


@pytest.mark.parametrize("role", NON_READERS + [Role.legal])
def test_only_an_admin_sees_or_decides_proposals(seeded, role):
    client = proposal_client(seeded, role)

    assert client.get("/governance/proposals").status_code == 403
    assert (
        client.post("/governance/proposals/p1", json={"status": "approved"}).status_code
        == 403
    )
