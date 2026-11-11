"""Org B must not be able to see, change or learn anything about org A through any route.

One test per route, generated from the app's own route list (see checks.py for what is
checked). The routers aren't org-aware yet, so most of these are expected to fail. Each
is marked with the block that fixes its router. When that block lands the test passes,
strict xfail turns that into a failure, and the marker comes off.
"""

from __future__ import annotations

import pytest

from tests.tenancy.checks import isolation_problems
from tests.tenancy.inventory import LANDED_BLOCKS
from tests.tenancy.routes import Route, real_routes

_, ROUTES = real_routes()

# Routes that already pass, so they must not be marked as expected failures. They are
# still tests: if one stops passing, that is a regression.
ALREADY_ISOLATED = {
    "POST /content/{content_id}/reviews": (
        "Only a creator can call it, and a creator already gets a 404 for content they "
        "don't own. Everyone else is refused by role."
    ),
    "POST /content/{content_id}/versions": "The same: creators get a 404, others a role refusal.",
    "POST /engine/eval/gate": (
        "It reads the rule from the caller's own rulebook, which Block 3 made per org, so "
        "another org's rule is a 404 like a missing one."
    ),
}


# Routes of an earlier block that call into a later block's code, so they pass when that
# block lands, not before.
DEPENDS_ON_LATER_BLOCK = {
    "POST /admin/facts/{fact_id}/rereview": (
        4,
        "It asks /memory/impact which pieces cite the fact, and that is Block 4's graph.",
    ),
}


def _expected_to_fail(route: Route):
    if route.name in DEPENDS_ON_LATER_BLOCK:
        block, reason = DEPENDS_ON_LATER_BLOCK[route.name]
        return (
            []
            if block in LANDED_BLOCKS
            else [pytest.mark.xfail(strict=True, reason=f"Block {block}: {reason}")]
        )
    if route.block in (3, 4) and route.block not in LANDED_BLOCKS and route.name not in ALREADY_ISOLATED:
        return [
            pytest.mark.xfail(
                strict=True,
                reason=f"Block {route.block} makes {route.prefix} org-aware. Remove the marker then.",
            )
        ]
    return []


@pytest.mark.parametrize(
    "route",
    [
        pytest.param(route, id=route.name, marks=_expected_to_fail(route))
        for route in ROUTES
    ],
)
def test_org_b_learns_nothing_about_org_a(
    route: Route, world, database, client_for, model_calls
):
    found, asked_about_ids = isolation_problems(
        route, world, database, client_for, model_calls
    )
    assert not found, (
        f"{route.name} isn't isolated"
        + (
            ""
            if asked_about_ids
            else " (it names no id, so the response and the database were checked)"
        )
        + ":\n  "
        + "\n  ".join(found)
    )
