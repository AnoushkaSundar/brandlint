"""The scoped helpers: the one correct way to query tenant data.

The helpers are tested on throwaway models with their own declarative base, so they
can't touch the app's tables. The last tests use the real User model and a real request.
"""

import pytest
from app.admin import models as admin_models  # noqa: F401
from app.auth.dependencies import SessionDep
from app.auth.models import Organization, User
from app.auth.security import create_token
from app.content import models as content_models  # noqa: F401
from app.db import Base, get_session
from app.tenancy import (
    NoOrg,
    NotTenantModel,
    OrgMismatch,
    bind_org,
    org_criterion,
    scoped,
    scoped_delete,
    scoped_get,
    scoped_join,
    scoped_update,
)
from app.tenancy.context import CurrentOrg
from app.workflow import models as workflow_models  # noqa: F401
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import String, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

A, B = "org-a", "org-b"


class Other(DeclarativeBase):
    """Not the app's Base, so these tables never appear in the app's metadata."""


class Widget(Other):
    __tablename__ = "widgets"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)


class Part(Other):
    __tablename__ = "parts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String)
    widget_id: Mapped[str] = mapped_column(String)


class Gadget(Other):
    """A key of several columns, with the org beside it."""

    __tablename__ = "gadgets"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String)


class Keyed(Other):
    """The org is part of the key, as rules and facts will be in Block 3."""

    __tablename__ = "keyed"
    org_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, primary_key=True)


class Note(Other):
    """Has no org_id, so it isn't tenant data and the helpers refuse it."""

    __tablename__ = "notes"
    id: Mapped[str] = mapped_column(String, primary_key=True)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Other.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        db.add_all(
            [
                Widget(id="w-a1", org_id=A, name="alpha"),
                Widget(id="w-a2", org_id=A, name="beta"),
                Widget(id="w-b1", org_id=B, name="alpha"),
                Part(id="p-a1", org_id=A, widget_id="w-a1"),
                Part(id="p-b1", org_id=B, widget_id="w-a1"),
                Gadget(id="g1", version="1", org_id=A),
                Gadget(id="g1", version="2", org_id=B),
                Keyed(org_id=A, id="r1", version="1"),
                Keyed(org_id=B, id="r1", version="1"),
                Note(id="n1"),
            ]
        )
        db.commit()
        yield db


def ids(rows) -> list[str]:
    return sorted(row.id for row in rows)


# scoped


def test_scoped_returns_only_the_orgs_rows(session):
    assert ids(session.scalars(scoped(session, Widget, org_id=A))) == ["w-a1", "w-a2"]
    assert ids(session.scalars(scoped(session, Widget, org_id=B))) == ["w-b1"]


def test_a_query_built_on_scoped_keeps_the_org_filter(session):
    query = scoped(session, Widget, org_id=A).where(Widget.name == "alpha")

    assert ids(session.scalars(query)) == ["w-a1"]


def test_scoped_takes_columns_and_aggregates(session):
    names = scoped(session, Widget, Widget.name, org_id=A).order_by(Widget.name)
    count = scoped(session, Widget, func.count(Widget.id), org_id=A)

    assert list(session.scalars(names)) == ["alpha", "beta"]
    assert session.scalar(count) == 2


def test_scoped_refuses_a_model_without_org_id(session):
    with pytest.raises(NotTenantModel, match="Note"):
        scoped(session, Note, org_id=A)


def test_a_shared_table_is_refused(session):
    """Organizations belong to nobody, so there is nothing to scope them by."""
    with pytest.raises(NotTenantModel, match="Organization"):
        scoped(session, Organization, org_id=A)


def test_scoped_needs_an_org(session):
    with pytest.raises(NoOrg):
        scoped(session, Widget)


def test_scoped_uses_the_org_bound_to_the_session(session):
    bind_org(session, A)

    assert ids(session.scalars(scoped(session, Widget))) == ["w-a1", "w-a2"]


def test_an_explicit_org_that_differs_from_the_bound_one_is_refused(session):
    bind_org(session, A)

    with pytest.raises(OrgMismatch):
        scoped(session, Widget, org_id=B)


def test_an_explicit_org_that_matches_the_bound_one_is_fine(session):
    bind_org(session, A)

    assert ids(session.scalars(scoped(session, Widget, org_id=A))) == ["w-a1", "w-a2"]


# scoped_get


def test_a_plain_get_ignores_the_org(session):
    """The reason scoped_get exists: Session.get can't be told which org to look in."""
    assert session.get(Widget, "w-b1") is not None


def test_scoped_get_finds_the_orgs_row(session):
    assert scoped_get(session, Widget, "w-a1", org_id=A).name == "alpha"


def test_scoped_get_answers_the_same_for_another_orgs_row_and_a_missing_one(session):
    assert scoped_get(session, Widget, "w-b1", org_id=A) is None
    assert scoped_get(session, Widget, "no-such-widget", org_id=A) is None


def test_scoped_get_takes_a_key_of_several_columns(session):
    assert scoped_get(session, Gadget, ("g1", "1"), org_id=A) is not None
    assert scoped_get(session, Gadget, ("g1", "2"), org_id=A) is None
    assert scoped_get(session, Gadget, ("g1", "2"), org_id=B) is not None


def test_scoped_get_when_the_org_is_part_of_the_key(session):
    assert scoped_get(session, Keyed, ("r1", "1"), org_id=A).org_id == A
    assert scoped_get(session, Keyed, ("r1", "1"), org_id=B).org_id == B


def test_scoped_get_checks_the_key_length(session):
    with pytest.raises(ValueError, match="2 values"):
        scoped_get(session, Gadget, "g1", org_id=A)


def test_scoped_get_refuses_a_model_without_org_id(session):
    with pytest.raises(NotTenantModel):
        scoped_get(session, Note, "n1", org_id=A)


# update, delete and join


def test_scoped_update_changes_only_the_orgs_rows(session):
    session.execute(scoped_update(session, Widget, org_id=A).values(name="changed"))
    session.commit()

    assert {w.id: w.name for w in session.scalars(select(Widget))} == {
        "w-a1": "changed",
        "w-a2": "changed",
        "w-b1": "alpha",
    }


def test_scoped_delete_removes_only_the_orgs_rows(session):
    session.execute(
        scoped_delete(session, Widget, org_id=A).where(Widget.name == "alpha")
    )
    session.commit()

    assert ids(session.scalars(select(Widget))) == ["w-a2", "w-b1"]


def test_scoped_join_leaves_out_the_other_orgs_joined_rows(session):
    """p-b1 points at an org A widget but belongs to org B, so org A must not see it."""
    query = scoped_join(
        scoped(session, Part, org_id=A).add_columns(Widget.name),
        session,
        Widget,
        Widget.id == Part.widget_id,
        org_id=A,
    )

    assert [(part.id, name) for part, name in session.execute(query)] == [
        ("p-a1", "alpha")
    ]


def test_scoped_join_refuses_a_model_without_org_id(session):
    with pytest.raises(NotTenantModel):
        scoped_join(
            scoped(session, Part, org_id=A), session, Note, Note.id == Part.id, org_id=A
        )


def test_org_criterion_is_the_filter_alone(session):
    query = select(Widget).where(org_criterion(session, Widget, org_id=B))

    assert ids(session.scalars(query)) == ["w-b1"]


# filling in the org on insert


def test_an_insert_without_an_org_gets_the_bound_one(session):
    bind_org(session, A)
    session.add(Widget(id="w-new", name="new"))
    session.commit()

    assert session.get(Widget, "w-new").org_id == A


def test_an_insert_for_another_org_is_refused(session):
    bind_org(session, A)
    session.add(Widget(id="w-new", name="new", org_id=B))

    with pytest.raises(OrgMismatch):
        session.flush()


def test_an_insert_for_the_bound_org_is_fine(session):
    bind_org(session, A)
    session.add(Widget(id="w-new", name="new", org_id=A))
    session.commit()

    assert session.get(Widget, "w-new").org_id == A


def test_an_insert_with_no_org_anywhere_is_never_guessed(session):
    """The column is NOT NULL, so the database refuses it."""
    session.add(Widget(id="w-new", name="new"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_a_session_with_no_bound_org_inserts_for_any_org(session):
    """Seeds and background jobs name the org themselves."""
    session.add(Widget(id="w-new", name="new", org_id=B))
    session.commit()

    assert session.get(Widget, "w-new").org_id == B


def test_models_without_org_id_are_left_alone(session):
    bind_org(session, A)
    session.add(Note(id="n2"))
    session.commit()

    assert session.get(Note, "n2") is not None


# a real request


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "a-test-only-secret-that-is-long-enough-for-hs256")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    with maker() as db:
        orgs = {
            slug: Organization(name=slug, slug=slug, kind="sandbox", status="active")
            for slug in ("one", "two")
        }
        db.add_all(orgs.values())
        db.flush()
        people = {
            f"{slug}-{n}": User(
                email=f"{slug}-{n}@x.test",
                name=f"{slug} {n}",
                password_hash="x",
                role="creator",
                org_id=org.id,
            )
            for slug, org in orgs.items()
            for n in (1, 2)
        }
        db.add_all(people.values())
        db.commit()

    app = FastAPI()

    @app.get("/people")
    def people_in_my_org(org: CurrentOrg, session: SessionDep) -> dict:
        return {
            "org": org.slug,
            "emails": sorted(
                user.email for user in session.scalars(scoped(session, User))
            ),
        }

    @app.post("/people")
    def add_person(
        org: CurrentOrg, session: SessionDep, other_org: str | None = None
    ) -> dict:
        user = User(
            email=f"new-{org.slug}@x.test",
            name="New",
            password_hash="x",
            role="creator",
            org_id=other_org,
        )
        session.add(user)
        session.flush()
        return {"org_id": user.org_id, "mine": org.id}

    def new_session():
        with maker() as db:
            yield db
            db.commit()

    app.dependency_overrides[get_session] = new_session
    client = TestClient(app)
    tokens = {name: create_token(user) for name, user in people.items()}
    return client, tokens, orgs


def test_current_org_is_the_signed_in_users_org(api):
    client, tokens, _ = api

    response = client.get(
        "/people", headers={"Authorization": f"Bearer {tokens['one-1']}"}
    )

    assert response.json() == {
        "org": "one",
        "emails": ["one-1@x.test", "one-2@x.test"],
    }


def test_each_org_sees_only_its_own_people(api):
    client, tokens, _ = api

    two = client.get(
        "/people", headers={"Authorization": f"Bearer {tokens['two-2']}"}
    ).json()

    assert two["emails"] == ["two-1@x.test", "two-2@x.test"]


def test_current_org_needs_a_signed_in_user(api):
    client, _, _ = api

    assert client.get("/people").status_code == 401


def test_a_row_added_in_a_request_goes_into_the_callers_org(api):
    client, tokens, orgs = api

    response = client.post(
        "/people", headers={"Authorization": f"Bearer {tokens['one-1']}"}
    )

    assert response.json() == {"org_id": orgs["one"].id, "mine": orgs["one"].id}


def test_a_request_cant_add_a_row_for_another_org(api):
    client, tokens, orgs = api

    with pytest.raises(OrgMismatch):
        client.post(
            "/people",
            params={"other_org": orgs["two"].id},
            headers={"Authorization": f"Bearer {tokens['one-1']}"},
        )


def test_the_session_stays_in_the_callers_org(api):
    """A second request from the other org isn't affected by the first."""
    client, tokens, _ = api
    client.get("/people", headers={"Authorization": f"Bearer {tokens['one-1']}"})

    two = client.get(
        "/people", headers={"Authorization": f"Bearer {tokens['two-1']}"}
    ).json()

    assert two["org"] == "two"


def test_a_plain_session_has_no_bound_org():
    with Session(create_engine("sqlite://")) as plain:
        assert plain.info.get("org_id") is None
