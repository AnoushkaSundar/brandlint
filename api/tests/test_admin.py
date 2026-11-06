"""The read-only brand data the engine depends on, and the gap log.

The API tests call the routes directly, because the UI hiding a fact proves nothing.
"""

from datetime import UTC, date, datetime

import app.content.models
import app.workflow.models  # noqa: F401
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
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda: 2)
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
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda: 2)
    session.add_all(
        [rule_row("R-1", 1, RuleStatus.approved), rule_row("R-1", 2, RuleStatus.draft)]
    )
    session.commit()

    assert rulebook_at(session)[0].version == 1


def test_a_retired_rule_stays_in_older_versions_only(session, monkeypatch):
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda: 2)
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
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda: 2)
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
    monkeypatch.setattr("app.admin.rulebook.current_rulebook_version", lambda: 2)
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
