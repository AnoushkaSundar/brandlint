"""Live review across API processes: two hubs joined by a wire, and the real Postgres bus."""

from __future__ import annotations

import asyncio
import copy
import os
import time

import pytest
from app import db
from app.collab import bus
from app.collab import hub as hub_module
from app.collab.hub import Hub, Person

LENA = Person("u-lena", "Lena", "reviewer")
MARCUS = Person("u-marcus", "Marcus", "reviewer")
DECISION = {
    "id": "d1",
    "finding_id": "f1",
    "actor": LENA.as_dict(),
    "action": "confirm_override",
    "status": "override_confirmed",
    "reason": None,
}


class Wire:
    """Joins hubs the way the bus joins processes: each gets what the others send."""

    def __init__(self, *hubs: Hub) -> None:
        self.hubs = hubs
        for each in hubs:
            each.attach(self.end(each))

    def end(self, owner: Hub):
        wire = self

        class End:
            def send(self, message):
                for other in wire.hubs:
                    if other is not owner:
                        other.receive(copy.deepcopy(message))

        return End()


@pytest.fixture()
def two():
    a, b = Hub(), Hub()
    Wire(a, b)
    return a, b


def test_an_event_on_one_process_reaches_a_stream_on_the_other(two):
    a, b = two

    async def run():
        subscriber, _, _ = b.subscribe("c", asyncio.get_running_loop(), None)
        a.publish("c", "decision", DECISION)
        return await asyncio.wait_for(subscriber.queue.get(), 1)

    event = asyncio.run(run())
    assert (event.name, event.data["actor"]["name"]) == ("decision", "Lena")
    assert [e.name for e in b.history("c")] == ["decision"]


def test_an_events_own_echo_is_ignored(two):
    a, _ = two
    a.publish("c", "state", {"to": "resolving"})
    a.receive({"t": "event", "o": a._origin, "c": "c", "n": "state", "d": {}, "i": 5})
    assert len(a.history("c")) == 1


def test_ids_rise_within_a_room_even_when_another_clock_is_behind(two):
    a, b = two
    first = a.publish("c", "state", {})
    b.receive({"t": "event", "o": "elsewhere", "c": "c", "n": "state", "d": {}, "i": 1})
    ids = [e.id for e in b.history("c")]
    assert ids == sorted(ids) and len(set(ids)) == 2
    assert first.id > 1_000_000  # clock-based once shared


def test_who_is_connected_on_another_process_is_shown_once(two):
    a, b = two
    a.connect("c", LENA)
    b.connect("c", MARCUS)
    assert {v["name"] for v in a.presence("c")["viewers"]} == {"Lena", "Marcus"}
    assert {v["name"] for v in b.presence("c")["viewers"]} == {"Lena", "Marcus"}
    # The same person with a stream on each process counts once.
    b.connect("c", LENA)
    assert [v["name"] for v in a.presence("c")["viewers"]].count("Lena") == 1


def test_two_people_on_one_finding_on_different_processes_is_contested(two):
    a, b = two
    a.connect("c", LENA)
    b.connect("c", MARCUS)
    a.focus("c", LENA, "f1")
    b.focus("c", MARCUS, "f1")
    assert a.presence("c")["contested"] == ["f1"]
    assert b.presence("c")["contested"] == ["f1"]


def test_a_focus_posted_to_the_other_process_still_counts(two):
    """The request can land on any process, while the person's stream is open on one."""
    a, b = two
    a.connect("c", LENA)  # Lena's stream is on A
    b.connect("c", MARCUS)
    b.focus("c", LENA, "f1")  # but her focus request reached B
    b.focus("c", MARCUS, "f1")
    assert a.presence("c")["contested"] == ["f1"]
    assert b.presence("c")["contested"] == ["f1"]


def test_leaving_one_process_is_seen_on_the_other(two):
    a, b = two
    a.connect("c", LENA)
    assert [v["name"] for v in b.presence("c")["viewers"]] == ["Lena"]
    a.disconnect("c", LENA)
    assert b.presence("c")["viewers"] == []


def test_a_process_that_goes_quiet_is_forgotten(two, monkeypatch):
    """A crashed process sends no goodbye, so its viewers expire."""
    a, b = two
    a.connect("c", LENA)
    monkeypatch.setattr(hub_module, "PRESENCE_TTL_S", 0.01)
    time.sleep(0.05)
    seen_before = len(b.history("c"))
    b.tick()
    assert b.presence("c")["viewers"] == []
    assert len(b.history("c")) == seen_before + 1  # and its streams were told


def test_a_heartbeat_keeps_a_quiet_but_alive_process_in_the_room(two, monkeypatch):
    a, b = two
    a.connect("c", LENA)
    monkeypatch.setattr(hub_module, "HEARTBEAT_S", 0.0)
    a.tick()  # resends who is connected here
    assert [v["name"] for v in b.presence("c")["viewers"]] == ["Lena"]


def test_a_ruling_on_one_process_clashes_with_one_on_another(two):
    a, b = two
    a.publish("c", "decision", DECISION)  # Lena settles f1 on process A
    clash = b.note_decision("c", "f1", MARCUS, "reject_override", "override_rejected")
    assert clash is not None
    assert (clash["first"]["person"]["name"], clash["second"]["person"]["name"]) == (
        "Lena",
        "Marcus",
    )


def test_a_browser_that_reconnects_to_a_process_that_saw_nothing_is_told_to_reload(two):
    _, b = two
    _, backlog, stale = b.subscribe("c", asyncio.new_event_loop(), last_id=12345)
    assert (backlog, stale) == ([], True)


def test_a_long_message_is_shortened_to_fit_a_notification():
    message = {
        "t": "event",
        "c": "c",
        "n": "decision",
        "d": {"reason": "x" * 20_000, "id": "d1"},
    }
    payload = bus._fit(message)
    assert len(payload.encode()) < bus.MAX_PAYLOAD
    assert '"id":"d1"' in payload


# --- The real bus, over Postgres LISTEN/NOTIFY -----------------------------------------

ADMIN_URL = os.environ.get("RLS_TEST_DATABASE_URL")
postgres = pytest.mark.skipif(
    not ADMIN_URL, reason="needs Postgres: set RLS_TEST_DATABASE_URL to a superuser URL"
)


def wait_for(check, seconds=8.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return False


@postgres
def test_two_processes_share_events_and_presence_through_postgres(monkeypatch):
    monkeypatch.setattr(db, "DATABASE_URL", ADMIN_URL)
    db.get_engine.cache_clear()
    a, b = Hub(), Hub()
    for each in (a, b):
        pg = bus.PgBus(each)
        each.attach(pg)
        pg.start()
        assert pg.ready.wait(10), "the listener never connected"
    try:
        a.publish("c", "decision", DECISION)
        assert wait_for(lambda: [e.name for e in b.history("c")] == ["decision"])
        a.connect("c", LENA)
        assert wait_for(
            lambda: [v["name"] for v in b.presence("c")["viewers"]] == ["Lena"]
        )
        a.disconnect("c", LENA)
        assert wait_for(lambda: b.presence("c")["viewers"] == [])
    finally:
        db.get_engine.cache_clear()
