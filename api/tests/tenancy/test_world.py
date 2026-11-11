"""The harness itself. These pass today, so a green isolation test can't be an empty one.

If these fail, the fixtures are broken and the isolation tests prove nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.db import Base
from sqlalchemy import func, select

from tests.tenancy import inventory
from tests.tenancy.inventory import TENANT_TABLES
from tests.tenancy.routes import (
    READ_AS,
    Route,
    call,
    normal_path,
    real_routes,
)

DOCS = Path(__file__).resolve().parents[3] / "docs" / "contracts.md"
# docs/contracts.md marks these as served by the mock only, so the real app doesn't have them.
MOCK_ONLY_IN_DOCS = {
    ("POST", "/engine/reviews"),
    ("POST", "/engine/reviews/{}/recheck"),
    ("POST", "/engine/findings/{}/fix"),
}

SPEC, ROUTES = real_routes()

GET_ROUTES = [route for route in ROUTES if route.method == "GET"]


def documented_routes() -> set[tuple[str, str]]:
    """Every `METHOD /path` in docs/contracts.md. A later `/path` in a row reuses the method."""
    found: set[tuple[str, str]] = set()
    for line in DOCS.read_text(encoding="utf-8").splitlines():
        method = None
        for token in re.findall(r"`([^`]+)`", line):
            match = re.match(r"(GET|POST|PUT|DELETE) (/[^\s?]*)", token)
            if match:
                method = match.group(1)
                found.add((method, normal_path(match.group(2))))
            elif method and re.match(r"/[\w/{}-]+$", token):
                found.add((method, normal_path(token)))
    return found


def test_both_orgs_have_data_in_every_tenant_table(world, database):
    """If a table were empty for an org, a leak from it would go unseen."""
    inventory.model_tables()
    with database.connect() as connection:
        counts = {
            name: connection.scalar(
                select(func.count()).select_from(Base.metadata.tables[name])
            )
            for name in TENANT_TABLES
        }
    empty = [name for name, count in counts.items() if count < 2]
    assert not empty, f"Both orgs need a row in these tables: {empty}"


def test_the_two_orgs_have_their_own_people_and_sentinels(world):
    assert world.a.marker != world.b.marker
    people = [person.id for org in (world.a, world.b) for person in org.people]
    assert len(set(people)) == 6
    assert not world.a.owned_ids & world.b.owned_ids


@pytest.mark.parametrize("route", GET_ROUTES, ids=lambda route: route.name)
def test_an_org_can_read_its_own_data(route: Route, world, client_for):
    """The positive half: org A's own people reach every read route with A's ids."""
    person = getattr(world.a, READ_AS.get(route.path, "admin"))
    response, _ = call(client_for(person), SPEC, route, world.a.ids)
    assert response.status_code == 200, (
        f"{route.name} answered {response.status_code}: {response.text[:200]}"
    )


def test_a_read_route_returns_the_orgs_own_sentinel(world, client_for):
    response, _ = call(
        client_for(world.a.admin), SPEC, Route("GET", "/admin/facts"), world.a.ids
    )
    assert world.a.marker in response.text


def test_the_route_list_comes_from_the_app_and_is_not_empty():
    assert len(ROUTES) > 40
    assert Route("GET", "/content/{content_id}") in ROUTES


def test_every_route_is_classified_into_a_block_or_exempt():
    unclassified = [route.name for route in ROUTES if route.block == -1]
    assert not unclassified, (
        f"No block is responsible for: {unclassified}. Add the router to "
        "BLOCK_BY_PREFIX in tests/tenancy/routes.py."
    )


def test_every_documented_route_exists():
    """docs/contracts.md must not promise a route the app doesn't serve."""
    if not DOCS.is_file():
        pytest.skip("docs/ isn't available here, for example in the API container")
    served = {(route.method, normal_path(route.path)) for route in ROUTES}
    documented = documented_routes()
    assert len(documented) >= 15, "The parser found too few routes in docs/contracts.md"
    missing = sorted(documented - served - MOCK_ONLY_IN_DOCS)
    assert not missing, (
        f"docs/contracts.md lists routes the app doesn't serve: {missing}"
    )


def test_the_isolation_check_passes_once_a_route_is_scoped(
    world, database, client_for, model_calls, monkeypatch
):
    """The check can be satisfied: scope one route by org and its problems disappear.

    Org membership is stood in for by the tag inside the fixture's ids (u-A-admin and
    c-A-1 are org A's). Without the change the same route is full of problems, which
    test_org_b_learns_nothing_about_org_a shows. Real scoping replaces this in Block 3.
    """
    import app.content.router as content_router
    from fastapi import HTTPException

    from tests.tenancy.checks import isolation_problems

    route = Route("GET", "/content/{content_id}")
    unscoped, _ = isolation_problems(route, world, database, client_for, model_calls)
    assert unscoped, "the unscoped route should leak, or this proves nothing"

    original = content_router.readable_content

    def scoped(content_id, user, session):
        content = original(content_id, user, session)
        if content.creator_id.split("-")[1] != user.id.split("-")[1]:
            raise HTTPException(404, "Content not found")
        return content

    monkeypatch.setattr(content_router, "readable_content", scoped)
    scoped_problems, _ = isolation_problems(
        route, world, database, client_for, model_calls
    )
    assert scoped_problems == []
