"""The live-review hub: who is on a piece of content, and what just happened to it.

It lives in this process. Events are published from request threads (a decision, a state
change, a comment) and read by SSE streams running on the event loop, so every change to
the rooms takes one lock, and delivery goes through `call_soon_threadsafe`.

Each room keeps the last `REPLAY` events, so a browser that reconnects with
`Last-Event-ID` catches up on what it missed. A browser too far behind is told to resync,
that is, to reload the board, instead of being sent a partial history.

Single process only. With more than one API worker, a decision made on one worker is not
seen by streams on another: that needs Postgres LISTEN/NOTIFY or Redis, and isn't built.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

REPLAY = 200
QUEUE_SIZE = 200
# Two different people deciding the same finding this close together is a conflict.
CONFLICT_WINDOW_S = 60.0
# A decision that leaves a finding waiting for a reviewer is a request, not a ruling, so
# the usual request-then-review is never a clash. Only two rulings can be.
WAITING = frozenset({"open", "override_pending", "fix_edited"})
# A room with nobody in it and nothing new is dropped after this long.
IDLE_S = 900.0


class Resync:
    """Put on a slow stream's queue instead of the events it couldn't keep up with."""


RESYNC = Resync()


@dataclass(frozen=True)
class Event:
    id: int
    name: str
    data: dict[str, Any]


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    role: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "role": self.role}


@dataclass
class Viewer:
    person: Person
    connections: int = 0
    finding_id: str | None = None


@dataclass(eq=False)  # compared by identity, so it can sit in a set
class Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))


@dataclass
class Room:
    seq: int = 0
    events: deque[Event] = field(default_factory=lambda: deque(maxlen=REPLAY))
    subscribers: set[Subscriber] = field(default_factory=set)
    viewers: dict[str, Viewer] = field(default_factory=dict)
    decided: dict[str, list[tuple[float, Person, str, str]]] = field(default_factory=dict)
    touched: float = field(default_factory=time.monotonic)


def _deliver(subscriber: Subscriber, item: Event | Resync) -> None:
    """Runs on the subscriber's loop. A full queue is replaced by one resync marker."""
    try:
        subscriber.queue.put_nowait(item)
    except asyncio.QueueFull:
        while not subscriber.queue.empty():
            subscriber.queue.get_nowait()
        subscriber.queue.put_nowait(RESYNC)


class Hub:
    def __init__(self, clock=time.time) -> None:
        self._lock = threading.Lock()
        self._rooms: dict[str, Room] = {}
        self._clock = clock

    # --- rooms -----------------------------------------------------------------------

    def _room(self, content_id: str) -> Room:
        room = self._rooms.get(content_id)
        if room is None:
            room = self._rooms[content_id] = Room()
        room.touched = time.monotonic()
        return room

    def _prune(self) -> None:
        now = time.monotonic()
        for key in [
            key
            for key, room in self._rooms.items()
            if not room.subscribers and not room.viewers and now - room.touched > IDLE_S
        ]:
            del self._rooms[key]

    def reset(self) -> None:
        """Forget everything. For tests."""
        with self._lock:
            self._rooms.clear()

    # --- events ----------------------------------------------------------------------

    def _publish(self, room: Room, name: str, data: dict[str, Any]) -> Event:
        room.seq += 1
        event = Event(room.seq, name, data)
        room.events.append(event)
        for subscriber in list(room.subscribers):
            try:
                subscriber.loop.call_soon_threadsafe(_deliver, subscriber, event)
            except RuntimeError:  # its loop has closed, so nobody is reading
                room.subscribers.discard(subscriber)
        return event

    def publish(self, content_id: str, name: str, data: dict[str, Any]) -> Event:
        with self._lock:
            self._prune()
            return self._publish(self._room(content_id), name, data)

    def history(self, content_id: str) -> list[Event]:
        """The events still held for a room, oldest first."""
        with self._lock:
            room = self._rooms.get(content_id)
            return list(room.events) if room else []

    def subscribe(
        self, content_id: str, loop: asyncio.AbstractEventLoop, last_id: int | None
    ) -> tuple[Subscriber, list[Event], bool]:
        """A subscription, the events it missed, and whether it missed too many to say."""
        subscriber = Subscriber(loop)
        with self._lock:
            room = self._room(content_id)
            room.subscribers.add(subscriber)
            if last_id is None:
                return subscriber, [], False
            oldest = room.events[0].id if room.events else room.seq + 1
            if last_id < oldest - 1 and room.seq > last_id:
                return subscriber, [], True
            return subscriber, [e for e in room.events if e.id > last_id], False

    def unsubscribe(self, content_id: str, subscriber: Subscriber) -> None:
        with self._lock:
            room = self._rooms.get(content_id)
            if room is not None:
                room.subscribers.discard(subscriber)

    # --- presence --------------------------------------------------------------------

    def _presence(self, room: Room) -> dict[str, Any]:
        viewers = [
            {**v.person.as_dict(), "finding_id": v.finding_id}
            for v in room.viewers.values()
        ]
        focused: dict[str, int] = {}
        for viewer in room.viewers.values():
            if viewer.finding_id:
                focused[viewer.finding_id] = focused.get(viewer.finding_id, 0) + 1
        return {
            "viewers": viewers,
            "contested": sorted(key for key, count in focused.items() if count > 1),
        }

    def presence(self, content_id: str) -> dict[str, Any]:
        with self._lock:
            return self._presence(self._room(content_id))

    def connect(self, content_id: str, person: Person) -> None:
        """A stream opened. The first one for a person announces them."""
        with self._lock:
            room = self._room(content_id)
            viewer = room.viewers.get(person.id)
            if viewer is None:
                viewer = room.viewers[person.id] = Viewer(person)
            viewer.connections += 1
            if viewer.connections == 1:
                self._publish(room, "presence", self._presence(room))

    def disconnect(self, content_id: str, person: Person) -> None:
        """A stream closed. When a person's last one does, they leave."""
        with self._lock:
            room = self._rooms.get(content_id)
            viewer = room.viewers.get(person.id) if room else None
            if room is None or viewer is None:
                return
            viewer.connections -= 1
            if viewer.connections <= 0:
                del room.viewers[person.id]
                self._publish(room, "presence", self._presence(room))

    def focus(self, content_id: str, person: Person, finding_id: str | None) -> dict[str, Any]:
        """Which finding a connected person is looking at. Others are told if it changed."""
        with self._lock:
            room = self._room(content_id)
            viewer = room.viewers.get(person.id)
            if viewer is not None and viewer.finding_id != finding_id:
                viewer.finding_id = finding_id
                self._publish(room, "presence", self._presence(room))
            return self._presence(room)

    # --- conflicts -------------------------------------------------------------------

    def note_decision(
        self,
        content_id: str,
        finding_id: str,
        person: Person,
        action: str,
        status: str,
    ) -> dict[str, Any] | None:
        """Records a ruling. Returns the conflict if someone else ruled on it just before.

        Only decisions that settle a finding count. A creator asking to override, or editing
        a fix, leaves it waiting for a reviewer, and the reviewer's answer is the normal
        next step. This can't know whether the second person had seen the first's ruling,
        so it says only what happened and leaves the call to them.
        """
        if status in WAITING:
            return None
        now = self._clock()
        with self._lock:
            room = self._room(content_id)
            earlier = [
                entry
                for entry in room.decided.get(finding_id, [])
                if now - entry[0] <= CONFLICT_WINDOW_S
            ]
            clash = next((entry for entry in reversed(earlier) if entry[1].id != person.id), None)
            earlier.append((now, person, action, status))
            room.decided[finding_id] = earlier
            if clash is None:
                return None
            _, first, first_action, first_status = clash
            return {
                "finding_id": finding_id,
                "first": {"person": first.as_dict(), "action": first_action, "status": first_status},
                "second": {"person": person.as_dict(), "action": action, "status": status},
                "within_seconds": round(now - clash[0], 1),
            }


hub = Hub()
