"""Live review: the hub, the commit hooks that feed it, the stream, and who may follow it."""

from __future__ import annotations

import asyncio
import threading

import app.admin.models  # noqa: F401
import pytest
from app.auth.models import Organization, User
from app.auth.router import router as auth_router
from app.auth.security import SESSION_COOKIE, create_token, hash_password
from app.collab import hub as hub_module
from app.collab import publish
from app.collab.hub import QUEUE_SIZE, REPLAY, RESYNC, Hub, Person
from app.collab.hub import hub as shared_hub
from app.collab.router import follow
from app.collab.router import router as collab_router
from app.content.models import Content, ContentVersion
from app.content.router import router as content_router
from app.db import Base, get_session
from app.workflow.models import Comment, Decision, Review, ReviewStateLog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

LENA = Person("u-lena", "Lena", "reviewer")
MARCUS = Person("u-marcus", "Marcus", "reviewer")
ORG = "00000000-0000-4000-8000-0000000000c1"


@pytest.fixture(autouse=True)
def clean_hub():
    shared_hub.reset()
    yield
    shared_hub.reset()


# --- The hub -----------------------------------------------------------------------------


def test_events_get_rising_ids_and_are_held_for_replay():
    hub = Hub()
    first = hub.publish("c", "decision", {"n": 1})
    second = hub.publish("c", "state", {"n": 2})
    assert (first.id, second.id) == (1, 2)
    assert [e.name for e in hub.history("c")] == ["decision", "state"]


def test_rooms_are_separate():
    hub = Hub()
    hub.publish("a", "decision", {})
    assert hub.history("b") == []


def test_a_reconnecting_stream_gets_only_what_it_missed():
    hub = Hub()
    for n in range(5):
        hub.publish("c", "decision", {"n": n})
    _, backlog, stale = hub.subscribe("c", asyncio.new_event_loop(), last_id=3)
    assert [e.id for e in backlog] == [4, 5]
    assert stale is False


def test_a_stream_with_nothing_missed_gets_nothing_and_a_new_one_starts_clean():
    hub = Hub()
    hub.publish("c", "decision", {})
    assert hub.subscribe("c", asyncio.new_event_loop(), last_id=1)[1] == []
    assert hub.subscribe("c", asyncio.new_event_loop(), last_id=None)[1:] == ([], False)


def test_a_stream_too_far_behind_is_told_to_resync_not_given_half_a_history():
    hub = Hub()
    for n in range(REPLAY + 20):
        hub.publish("c", "decision", {"n": n})
    _, backlog, stale = hub.subscribe("c", asyncio.new_event_loop(), last_id=1)
    assert (backlog, stale) == ([], True)


def test_a_slow_stream_is_replaced_by_a_resync_marker():
    hub = Hub()

    async def run():
        loop = asyncio.get_running_loop()
        subscriber, _, _ = hub.subscribe("c", loop, None)
        for n in range(QUEUE_SIZE + 5):
            hub.publish("c", "decision", {"n": n})
        await asyncio.sleep(0.1)
        return [subscriber.queue.get_nowait() for _ in range(subscriber.queue.qsize())]

    items = asyncio.run(run())
    assert RESYNC in items
    assert len(items) <= QUEUE_SIZE


def test_a_closed_loop_drops_its_subscriber_instead_of_breaking_the_publisher():
    hub = Hub()
    loop = asyncio.new_event_loop()
    hub.subscribe("c", loop, None)
    loop.close()
    hub.publish("c", "decision", {})  # must not raise
    assert hub._rooms["c"].subscribers == set()


def test_presence_announces_the_first_stream_and_the_last_to_close():
    hub = Hub()
    hub.connect("c", LENA)
    hub.connect("c", LENA)  # a second tab
    hub.connect("c", MARCUS)
    names = [e.data["viewers"] for e in hub.history("c") if e.name == "presence"]
    assert [len(v) for v in names] == [1, 2]  # the second tab said nothing
    hub.disconnect("c", LENA)
    assert [v["name"] for v in hub.presence("c")["viewers"]] == ["Lena", "Marcus"]
    hub.disconnect("c", LENA)
    assert [v["name"] for v in hub.presence("c")["viewers"]] == ["Marcus"]


def test_two_people_on_one_finding_is_contested():
    hub = Hub()
    hub.connect("c", LENA)
    hub.connect("c", MARCUS)
    hub.focus("c", LENA, "f1")
    assert hub.presence("c")["contested"] == []
    hub.focus("c", MARCUS, "f1")
    assert hub.presence("c")["contested"] == ["f1"]
    hub.focus("c", MARCUS, "f2")
    assert hub.presence("c")["contested"] == []


def test_focus_only_counts_for_someone_with_an_open_stream():
    hub = Hub()
    hub.focus("c", LENA, "f1")
    assert hub.presence("c")["viewers"] == []


def test_an_unchanged_focus_is_not_announced_again():
    hub = Hub()
    hub.connect("c", LENA)
    hub.focus("c", LENA, "f1")
    before = len(hub.history("c"))
    hub.focus("c", LENA, "f1")
    assert len(hub.history("c")) == before


def test_two_people_settling_the_same_finding_close_together_is_a_conflict():
    clock = iter([100.0, 110.0])
    hub = Hub(clock=lambda: next(clock))
    assert hub.note_decision("c", "f1", LENA, "confirm_override", "override_confirmed") is None
    clash = hub.note_decision("c", "f1", MARCUS, "reject_override", "override_rejected")
    assert clash["finding_id"] == "f1"
    assert clash["first"]["person"]["name"] == "Lena"
    assert clash["second"]["action"] == "reject_override"
    assert clash["within_seconds"] == 10.0


def test_a_request_followed_by_a_reviewers_answer_is_the_normal_flow_not_a_conflict():
    clock = iter([100.0, 105.0])
    hub = Hub(clock=lambda: next(clock))
    assert hub.note_decision("c", "f1", Person("u-c", "Priya", "creator"), "override", "override_pending") is None
    assert hub.note_decision("c", "f1", LENA, "confirm_override", "override_confirmed") is None


def test_a_request_never_counts_as_the_first_ruling_either():
    clock = iter([100.0, 101.0, 102.0])
    hub = Hub(clock=lambda: next(clock))
    hub.note_decision("c", "f1", LENA, "confirm_override", "override_confirmed")
    # Marcus only edits a fix, which leaves it waiting: that isn't a second ruling.
    assert hub.note_decision("c", "f1", MARCUS, "edit_fix", "fix_edited") is None
    assert hub.note_decision("c", "f1", MARCUS, "reject_override", "override_rejected") is not None


def test_the_same_person_deciding_twice_is_not_a_conflict():
    clock = iter([100.0, 101.0])
    hub = Hub(clock=lambda: next(clock))
    hub.note_decision("c", "f1", LENA, "override", "override_pending")
    assert hub.note_decision("c", "f1", LENA, "override", "override_pending") is None


def test_decisions_far_apart_or_on_different_findings_are_not_conflicts():
    clock = iter([100.0, 400.0, 401.0])
    hub = Hub(clock=lambda: next(clock))
    hub.note_decision("c", "f1", LENA, "resolve", "resolved")
    assert hub.note_decision("c", "f1", MARCUS, "resolve", "resolved") is None  # 300 s later
    assert hub.note_decision("c", "f2", LENA, "resolve", "resolved") is None


def test_many_threads_publishing_never_repeat_or_skip_an_id():
    hub = Hub()

    def work():
        for _ in range(50):
            hub.publish("c", "decision", {})

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ids = [e.id for e in hub.history("c")]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert hub._rooms["c"].seq == 400


# --- The stream --------------------------------------------------------------------------


def parse(frames: list[str]) -> list[tuple[str, dict]]:
    import json

    out = []
    for frame in frames:
        lines = dict(line.split(": ", 1) for line in frame.strip().splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


async def collect(room, content_id, person, *, last_id=None, stop_after=None, ping=15.0):
    frames: list[str] = []
    done = {"now": False}

    async def disconnected():
        return done["now"]

    stream = follow(room, content_id, person, last_id, disconnected, ping=ping)
    async for chunk in stream:
        frames.append(chunk)
        if stop_after and len(parse(frames)) >= stop_after:
            done["now"] = True
            break
    await stream.aclose()
    return frames


def test_the_stream_opens_with_who_is_here_and_who_you_are():
    hub = Hub()
    frames = asyncio.run(collect(hub, "c", LENA, stop_after=1))
    assert frames[0] == "retry: 3000\n\n"
    name, data = parse(frames)[0]
    assert name == "hello"
    assert data["you"]["name"] == "Lena"
    assert [v["name"] for v in data["viewers"]] == ["Lena"]


def test_a_decision_published_from_another_thread_reaches_an_open_stream():
    hub = Hub()

    async def run():
        task = asyncio.create_task(collect(hub, "c", LENA, stop_after=3))
        await asyncio.sleep(0.05)
        await asyncio.to_thread(
            hub.publish, "c", "decision", {"finding_id": "f1", "actor": MARCUS.as_dict()}
        )
        return await asyncio.wait_for(task, 5)

    names = [name for name, _ in parse(asyncio.run(run()))]
    assert names[0] == "hello" and "decision" in names


def test_the_stream_replays_what_a_reconnecting_browser_missed():
    hub = Hub()
    for n in range(4):
        hub.publish("c", "decision", {"n": n})
    frames = asyncio.run(collect(hub, "c", LENA, last_id=2, stop_after=3))
    events = [(n, d) for n, d in parse(frames) if n == "decision"]
    assert [d["n"] for _, d in events] == [2, 3]
    assert "id: 3\n" in "".join(frames)


def test_a_stream_too_far_behind_says_resync():
    hub = Hub()
    for n in range(REPLAY + 10):
        hub.publish("c", "decision", {"n": n})
    names = [n for n, _ in parse(asyncio.run(collect(hub, "c", LENA, last_id=1, stop_after=2)))]
    assert names[:2] == ["hello", "resync"]


def test_an_idle_stream_pings_so_a_proxy_keeps_it_open():
    hub = Hub()
    frames = asyncio.run(_ping_then_stop(hub))
    assert ": ping\n\n" in frames


async def _ping_then_stop(hub):
    frames: list[str] = []
    seen = {"pings": 0}

    async def disconnected():
        return seen["pings"] >= 1

    async for chunk in follow(hub, "c", LENA, None, disconnected, ping=0.02):
        frames.append(chunk)
        seen["pings"] += chunk.startswith(": ping")
    return frames


def test_leaving_removes_you_and_tells_the_others():
    hub = Hub()
    hub.connect("c", MARCUS)
    asyncio.run(collect(hub, "c", LENA, stop_after=1))
    assert [v["name"] for v in hub.presence("c")["viewers"]] == ["Marcus"]
    last = [e for e in hub.history("c") if e.name == "presence"][-1]
    assert [v["name"] for v in last.data["viewers"]] == ["Marcus"]


def test_a_stream_that_ends_by_error_still_leaves_the_room():
    hub = Hub()

    async def run():
        stream = follow(hub, "c", LENA, None, lambda: asyncio.sleep(0, result=False))
        await stream.__anext__()
        await stream.aclose()

    asyncio.run(run())
    assert hub.presence("c")["viewers"] == []
    assert hub._rooms["c"].subscribers == set()


# --- The commit hooks --------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/collab.db")
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    with maker() as session:
        session.add(Organization(id=ORG, name="Org", slug="org", kind="sandbox", status="active"))
        for ident, name, role in (
            ("u-creator", "Priya", "creator"), ("u-lena", "Lena", "reviewer"),
            ("u-marcus", "Marcus", "reviewer"), ("u-other", "Sam", "creator"),
        ):
            session.add(User(
                id=ident, email=f"{ident}@x.y", name=name, role=role, org_id=ORG,
                password_hash=hash_password("x"),
            ))
        session.add(Content(
            id="content-1", title="Blog", channel="blog", source="agency",
            data_class="public", creator_id="u-creator",
        ))
        session.add(ContentVersion(
            id="v1", content_id="content-1", version=1, text="Hi", created_by="u-creator"
        ))
        session.add(Review(
            id="r1", content_version_id="v1", engine_review_id="rev-1", channel="blog",
            rulebook_version=1,
        ))
        session.commit()
        yield session


def decision(actor="u-lena", finding="f1", action="confirm_override", status="override_confirmed"):
    return Decision(
        review_id="r1", finding_id=finding, actor_id=actor, role="reviewer", action=action,
        status=status, reason="Fine in a quote.",
    )


def published(name=None):
    return [e for e in shared_hub.history("content-1") if name is None or e.name == name]


def test_a_committed_decision_is_published_with_who_made_it(db):
    db.add(decision())
    assert published() == []  # nothing before the commit
    db.commit()
    [event] = published("decision")
    assert event.data["finding_id"] == "f1"
    assert event.data["actor"] == {"id": "u-lena", "name": "Lena", "role": "reviewer"}
    assert (event.data["action"], event.data["status"]) == ("confirm_override", "override_confirmed")
    assert event.data["reason"] == "Fine in a quote."


def test_a_rolled_back_decision_publishes_nothing_and_does_not_leak_into_the_next(db):
    db.add(decision())
    db.flush()
    db.rollback()
    db.add(ReviewStateLog(
        content_id="content-1", from_state="resolving", to_state="reviewer_check",
        actor_id="u-creator",
    ))
    db.commit()
    assert [e.name for e in published()] == ["state"]


def test_a_state_change_is_published(db):
    db.add(ReviewStateLog(
        content_id="content-1", from_state="resolving", to_state="reviewer_check",
        actor_id="u-creator", reason="Ready",
    ))
    db.commit()
    [event] = published("state")
    assert (event.data["from"], event.data["to"]) == ("resolving", "reviewer_check")
    assert event.data["actor"]["name"] == "Priya"


def test_a_comment_is_published_without_its_text(db):
    db.add(Comment(content_version_id="v1", finding_id="f1", author_id="u-lena", body="A secret remark"))
    db.commit()
    [event] = published("comment")
    assert event.data["actor"]["name"] == "Lena"
    assert "secret" not in str(event.data)


def test_two_reviewers_settling_one_finding_raises_a_conflict_naming_both(db):
    db.add(decision("u-lena", status="override_confirmed"))
    db.commit()
    db.add(decision("u-marcus", action="reject_override", status="override_rejected"))
    db.commit()
    [clash] = published("conflict")
    assert clash.data["first"]["person"]["name"] == "Lena"
    assert clash.data["second"]["person"]["name"] == "Marcus"


def test_a_failure_while_publishing_never_fails_the_decision(db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("hub down")

    monkeypatch.setattr(hub_module.hub, "publish", boom)
    monkeypatch.setattr(publish, "hub", hub_module.hub)
    db.add(decision())
    db.commit()  # must not raise
    assert db.query(Decision).count() == 1


def test_a_decision_for_a_review_that_is_gone_is_skipped(db):
    db.add(Decision(
        review_id="r1", finding_id="f1", actor_id="u-lena", role="reviewer", action="resolve",
        status="resolved",
    ))
    db.commit()
    db.query(Review).delete()
    db.commit()
    db.add(decision(finding="f2"))
    db.commit()  # the lookup finds no review, and that's not an error


# --- Who may follow ----------------------------------------------------------------------


@pytest.fixture()
def api(db):
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(content_router)
    app.include_router(collab_router)
    app.dependency_overrides[get_session] = lambda: db

    def as_(user_id):
        client = TestClient(app)
        client.cookies.set(SESSION_COOKIE, create_token(db.get(User, user_id)))
        return client

    return as_


def test_nobody_signed_out_can_follow_a_piece(api):
    assert TestClient(api("u-lena").app).get("/collab/content/content-1/presence").status_code == 401


def test_the_owner_and_reviewers_can_see_who_is_here(api):
    for user in ("u-creator", "u-lena"):
        assert api(user).get("/collab/content/content-1/presence").status_code == 200


def test_another_creator_gets_a_404_not_a_peek(api):
    client = api("u-other")
    assert client.get("/collab/content/content-1/presence").status_code == 404
    assert client.post("/collab/content/content-1/presence", json={"finding_id": "f1"}).status_code == 404


def test_a_missing_piece_is_a_404_for_everyone(api):
    assert api("u-lena").get("/collab/content/nope/presence").status_code == 404


def test_focusing_a_finding_needs_an_open_stream(api):
    reply = api("u-lena").post("/collab/content/content-1/presence", json={"finding_id": "f1"})
    assert reply.status_code == 200
    assert reply.json()["viewers"] == []


def test_a_bad_focus_body_is_refused(api):
    assert api("u-lena").post("/collab/content/content-1/presence", json={"finding_id": 5}).status_code == 422
