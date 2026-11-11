"""The isolation check for one route, shared by the route test and the harness self-test.

Org B calls the route as each of its people, twice: with org A's real ids and with ids
that exist nowhere. A is only safe when the two answers are the same, because then B
can't tell that A's row exists. On top of that:

- the response must not contain org A's data, or any other id of A's;
- whatever B writes carries a unique write marker, and org A reading every route
  afterwards must never see it;
- no row of A's may be changed or deleted, and no new row may refer to A;
- nothing of A's may be sent to a model on B's behalf.
"""

from __future__ import annotations

import uuid

from tests.tenancy import state
from tests.tenancy.routes import (
    READ_AS,
    Route,
    call,
    fake_ids,
    real_routes,
    write_needles,
)

PREVIEW = 160


def bad_request(response) -> bool:
    """FastAPI refused the request's shape. A handler's own 422 is an answer, not a fault."""
    if response.status_code != 422:
        return False
    try:
        return isinstance(response.json().get("detail"), list)
    except ValueError:
        return False


def _flatten(ids: dict) -> list[str]:
    values: list[str] = []
    for value in ids.values():
        values.extend(value if isinstance(value, list) else [value])
    return values


def _shape(response, ids: list[str]) -> tuple[int, str]:
    """A response with the ids taken out, so two answers that differ only by id compare equal."""
    text = response.text
    for identifier in sorted(ids, key=len, reverse=True):
        text = text.replace(identifier, "<id>")
    return response.status_code, text


def isolation_problems(
    route: Route, world, database, client_for, model_calls
) -> tuple[list[str], bool]:
    """What org B managed to learn or change through one route. Empty means isolated.

    Also says whether the route took any id, for the report.
    """
    spec, routes = real_routes()
    a, b = world.a, world.b
    nowhere = fake_ids(a.ids)
    sent = _flatten(a.ids)
    ids = sorted(sent + _flatten(nowhere), key=len, reverse=True)
    other_ids_of_a = [i for i in a.owned_ids if i not in sent]
    write = f"WRITE-{uuid.uuid4().hex[:12]}"
    before = state.snapshot(database)
    found: list[str] = []
    reached = False
    asked_about_ids = False

    for person in b.people:
        client = client_for(person)
        who = person.role
        sent_before = len(model_calls)
        missing, _ = call(client, spec, route, nowhere, write)
        real, uses_ids = call(client, spec, route, a.ids, write)
        asked_about_ids = asked_about_ids or uses_ids

        if a.marker in real.text:
            found.append(f"{who}: the response contains org A's data")
        leaked = [i for i in other_ids_of_a if i in real.text]
        if leaked:
            found.append(
                f"{who}: the response names other ids of org A: {sorted(leaked)}"
            )
        if any(a.marker in text for text in model_calls[sent_before:]):
            found.append(f"{who}: org A's text was sent to a model on org B's behalf")
        for label, response in (("a nonexistent id", missing), ("org A's id", real)):
            if bad_request(response):
                found.append(
                    f"{who}: {label} failed validation (422), so the route wasn't tested. "
                    "Fix the request in tests/tenancy/routes.py"
                )
        # The harness refuses most model calls, so a 500 right after one isn't the route's fault.
        if real.status_code >= 500 and len(model_calls) == sent_before:
            found.append(
                f"{who}: org A's id caused a server error ({real.status_code})"
            )
        if uses_ids and _shape(real, ids) != _shape(missing, ids):
            found.append(
                f"{who}: org A's id was answered {real.status_code} {real.text[:PREVIEW]!r}, "
                f"but a nonexistent id was answered {missing.status_code} {missing.text[:PREVIEW]!r}"
            )
        reached = reached or real.status_code not in (401, 403)

    if route.block is not None and not reached:
        found.append("no person in org B could reach this route, so it wasn't tested")
    found += state.problems(before, state.snapshot(database), a.owned_ids)

    # Now org A looks at everything it can read. Nothing B wrote may be there.
    for read in (r for r in routes if r.method == "GET"):
        person = getattr(a, READ_AS.get(read.path, "admin"))
        seen, _ = call(client_for(person), spec, read, a.ids)
        if any(needle in seen.text for needle in write_needles(write)):
            found.append(f"org A can read what org B wrote, in {read.name}")
    return found, asked_about_ids
