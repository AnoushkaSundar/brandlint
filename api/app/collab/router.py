"""Live review: a stream of what happens to a piece of content, and who is looking at it.

Anyone who may read the content may follow it, by the same rule as the content itself, so
another creator or another org gets a 404 here as everywhere else.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import app.collab.publish  # noqa: F401  registers the commit hooks
from app.auth.dependencies import CurrentUser, SessionDep, current_user
from app.collab.hub import RESYNC, Event, Hub, Person, hub
from app.content.access import readable_content

PING_S = 15.0

router = APIRouter(
    prefix="/collab", tags=["collab"], dependencies=[Depends(current_user)]
)


class Focus(BaseModel):
    finding_id: str | None = None


def frame(name: str, data: dict, event_id: int | None = None) -> str:
    lines = [f"id: {event_id}"] if event_id is not None else []
    lines += [f"event: {name}", f"data: {json.dumps(data)}"]
    return "\n".join(lines) + "\n\n"


def _frame_event(event: Event) -> str:
    return frame(event.name, event.data, event.id)


async def follow(
    room: Hub,
    content_id: str,
    person: Person,
    last_id: int | None,
    disconnected: Callable[[], Awaitable[bool]],
    ping: float = PING_S,
) -> AsyncIterator[str]:
    """The stream for one connection. It leaves the room however it ends."""
    subscriber, backlog, stale = room.subscribe(
        content_id, asyncio.get_running_loop(), last_id
    )
    room.connect(content_id, person)
    try:
        yield "retry: 3000\n\n"
        yield frame("hello", {"you": person.as_dict(), **room.presence(content_id)})
        if stale:
            yield frame("resync", {})
        for event in backlog:
            yield _frame_event(event)
        while not await disconnected():
            try:
                item = await asyncio.wait_for(subscriber.queue.get(), ping)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if item is RESYNC:
                yield frame("resync", {})
                return
            yield _frame_event(item)
    finally:
        room.unsubscribe(content_id, subscriber)
        room.disconnect(content_id, person)


def _person(user) -> Person:
    return Person(user.id, user.name, user.role)


def _last_id(header: str | None) -> int | None:
    try:
        return int(header) if header else None
    except ValueError:
        return None


@router.get("/content/{content_id}/events")
async def events(
    content_id: str,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    await run_in_threadpool(readable_content, content_id, user, session)
    person = _person(user)  # copied now: the session is closed by the time this streams
    body = follow(hub, content_id, person, _last_id(last_event_id), request.is_disconnected)
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        # No buffering, so a proxy hands each event over as it happens.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/content/{content_id}/presence")
def presence(content_id: str, user: CurrentUser, session: SessionDep) -> dict:
    readable_content(content_id, user, session)
    return hub.presence(content_id)


@router.post("/content/{content_id}/presence")
def look_at(content_id: str, body: Focus, user: CurrentUser, session: SessionDep) -> dict:
    """Which finding the caller is looking at. Only counts while their stream is open."""
    readable_content(content_id, user, session)
    return hub.focus(content_id, _person(user), body.finding_id)
