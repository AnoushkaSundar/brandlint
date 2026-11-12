"""The live-review hub: who is on a piece of content, and what just happened to it.

Events are published from request threads (a decision, a state change, a comment) and read
by SSE streams running on the event loop, so every change to the rooms takes one lock, and
delivery goes through `call_soon_threadsafe`.

Each room keeps the last `REPLAY` events, so a browser that reconnects with
`Last-Event-ID` catches up on what it missed. A browser too far behind, or one that
reconnects to a process that never saw its events, is told to resync, that is, to reload
the board, instead of being sent a partial history.

**Several API processes.** A hub can be given a transport (`attach`), which carries what it
publishes to the other processes and hands their messages to `receive`. `bus.py` is the
real one, over Postgres LISTEN/NOTIFY. Without one, the hub works alone, as in a single
process or in tests. Across processes:

- Events are applied here at once and sent on. Their ids come from the clock (and rise
  within a room), because every process numbers them on its own.
- Presence is shared as each process's own viewers, resent every `HEARTBEAT_S`. What a
  process hasn't heard for `PRESENCE_TTL_S` is dropped, so a crashed process doesn't leave
  ghosts. A person with a stream open on two processes counts once.
- A decision made on another process is remembered here too, so the conflict check sees
  it. The process that records the second ruling is the one that announces the conflict.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

REPLAY = 200
QUEUE_SIZE = 200
# Two different people deciding the same finding this close together is a conflict.
CONFLICT_WINDOW_S = 60.0
# A decision that leaves a finding waiting for a reviewer is a request, not a ruling, so
# the usual request-then-review is never a clash. Only two rulings can be.
WAITING = frozenset({"open", "override_pending", "fix_edited"})
# A room with nobody in it and nothing new is dropped after this long.
IDLE_S = 900.0
# Another process's viewers are resent this often, and forgotten when not heard for the TTL.
HEARTBEAT_S = 10.0
PRESENCE_TTL_S = 30.0


class Resync:
    """Put on a slow stream's queue instead of the events it couldn't keep up with."""


RESYNC = Resync()


class Transport(Protocol):
    def send(self, message: dict[str, Any]) -> None: ...


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
    # Other processes' viewers: origin -> (when we last heard, who they have)
    remote: dict[str, tuple[float, list[dict[str, Any]]]] = field(default_factory=dict)
    decided: dict[str, list[tuple[float, Person, str, str]]] = field(
        default_factory=dict
    )
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
        self._origin = uuid.uuid4().hex
        self._transport: Transport | None = None
        self._last_heartbeat = 0.0

    # --- other processes -------------------------------------------------------------

    def attach(self, transport: Transport) -> None:
        """Share this hub with the other API processes through `transport`."""
        self._transport = transport

    @property
    def shared(self) -> bool:
        return self._transport is not None

    def _send(self, *messages: dict[str, Any]) -> None:
        """Hand messages to the transport. Never called with the lock held."""
        if self._transport is None:
            return
        for message in messages:
            try:
                self._transport.send(message)
            except Exception:
                logger.warning("could not share a live-review message", exc_info=True)

    def _next_id(self, room: Room) -> int:
        if self._transport is None:
            return room.seq + 1
        # Every process numbers its own events, so the clock keeps them comparable.
        return max(room.seq + 1, time.time_ns() // 1000)

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
            if not room.subscribers
            and not room.viewers
            and not room.remote
            and now - room.touched > IDLE_S
        ]:
            del self._rooms[key]

    def reset(self) -> None:
        """Forget everything. For tests."""
        with self._lock:
            self._rooms.clear()

    def resync_all(self) -> None:
        """Tell every open stream to reload, because messages may have been missed."""
        with self._lock:
            for room in self._rooms.values():
                for subscriber in list(room.subscribers):
                    try:
                        subscriber.loop.call_soon_threadsafe(
                            _deliver, subscriber, RESYNC
                        )
                    except RuntimeError:
                        room.subscribers.discard(subscriber)

    # --- events ----------------------------------------------------------------------

    def _append(self, room: Room, event: Event) -> Event:
        room.seq = event.id
        room.events.append(event)
        for subscriber in list(room.subscribers):
            try:
                subscriber.loop.call_soon_threadsafe(_deliver, subscriber, event)
            except RuntimeError:  # its loop has closed, so nobody is reading
                room.subscribers.discard(subscriber)
        return event

    def _publish(self, room: Room, name: str, data: dict[str, Any]) -> Event:
        """An event for this process's own streams only."""
        return self._append(room, Event(self._next_id(room), name, data))

    def publish(self, content_id: str, name: str, data: dict[str, Any]) -> Event:
        with self._lock:
            self._prune()
            event = self._publish(self._room(content_id), name, data)
        self._send(
            {
                "t": "event",
                "o": self._origin,
                "c": content_id,
                "n": name,
                "d": data,
                "i": event.id,
            }
        )
        return event

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
            if not room.events:
                # It has seen an event, and this process holds none for the room: they were
                # lost (a restart) or went to another process. It can't be told which.
                return subscriber, [], True
            oldest = room.events[0].id
            if last_id < oldest - 1 and room.seq > last_id:
                return subscriber, [], True
            return subscriber, [e for e in room.events if e.id > last_id], False

    def unsubscribe(self, content_id: str, subscriber: Subscriber) -> None:
        with self._lock:
            room = self._rooms.get(content_id)
            if room is not None:
                room.subscribers.discard(subscriber)

    # --- presence --------------------------------------------------------------------

    def _viewers(self, room: Room, fresh_only: bool = True) -> list[dict[str, Any]]:
        """Everyone with a stream open here or, as last heard, on another process."""
        merged = {
            v.person.id: {**v.person.as_dict(), "finding_id": v.finding_id}
            for v in room.viewers.values()
        }
        now = time.monotonic()
        for seen, viewers in room.remote.values():
            if fresh_only and now - seen > PRESENCE_TTL_S:
                continue
            for viewer in viewers:
                merged.setdefault(viewer["id"], viewer)
        return list(merged.values())

    def _presence(self, room: Room, fresh_only: bool = True) -> dict[str, Any]:
        viewers = self._viewers(room, fresh_only)
        focused: dict[str, int] = {}
        for viewer in viewers:
            if viewer.get("finding_id"):
                focused[viewer["finding_id"]] = focused.get(viewer["finding_id"], 0) + 1
        return {
            "viewers": viewers,
            "contested": sorted(key for key, count in focused.items() if count > 1),
        }

    def _share_presence(self, content_id: str, room: Room) -> dict[str, Any]:
        """The message that tells other processes who is connected to this one."""
        return {
            "t": "presence",
            "o": self._origin,
            "c": content_id,
            "v": [
                {**v.person.as_dict(), "finding_id": v.finding_id}
                for v in room.viewers.values()
            ],
        }

    def presence(self, content_id: str) -> dict[str, Any]:
        with self._lock:
            return self._presence(self._room(content_id))

    def connect(self, content_id: str, person: Person) -> None:
        """A stream opened. The first one for a person announces them."""
        message = None
        with self._lock:
            room = self._room(content_id)
            viewer = room.viewers.get(person.id)
            if viewer is None:
                viewer = room.viewers[person.id] = Viewer(person)
            viewer.connections += 1
            if viewer.connections == 1:
                self._publish(room, "presence", self._presence(room))
                message = self._share_presence(content_id, room)
        if message:
            self._send(message)

    def disconnect(self, content_id: str, person: Person) -> None:
        """A stream closed. When a person's last one does, they leave."""
        message = None
        with self._lock:
            room = self._rooms.get(content_id)
            viewer = room.viewers.get(person.id) if room else None
            if room is None or viewer is None:
                return
            viewer.connections -= 1
            if viewer.connections <= 0:
                del room.viewers[person.id]
                self._publish(room, "presence", self._presence(room))
                message = self._share_presence(content_id, room)
        if message:
            self._send(message)

    def focus(
        self, content_id: str, person: Person, finding_id: str | None
    ) -> dict[str, Any]:
        """Which finding a connected person is looking at. Others are told if it changed."""
        message = None
        with self._lock:
            room = self._room(content_id)
            viewer = room.viewers.get(person.id)
            if viewer is not None and viewer.finding_id != finding_id:
                viewer.finding_id = finding_id
                self._publish(room, "presence", self._presence(room))
                message = self._share_presence(content_id, room)
            elif viewer is None:
                # Their stream may be open on another process, which is the one to record it.
                message = {
                    "t": "focus",
                    "o": self._origin,
                    "c": content_id,
                    "p": person.as_dict(),
                    "f": finding_id,
                }
            result = self._presence(room)
        if message:
            self._send(message)
        return result

    # --- conflicts -------------------------------------------------------------------

    def _remember(
        self, room: Room, finding_id: str, person: Person, action: str, status: str
    ) -> dict[str, Any] | None:
        """Records a ruling, and returns the conflict if someone else ruled just before."""
        now = self._clock()
        earlier = [
            entry
            for entry in room.decided.get(finding_id, [])
            if now - entry[0] <= CONFLICT_WINDOW_S
        ]
        clash = next(
            (entry for entry in reversed(earlier) if entry[1].id != person.id), None
        )
        earlier.append((now, person, action, status))
        room.decided[finding_id] = earlier
        if clash is None:
            return None
        _, first, first_action, first_status = clash
        return {
            "finding_id": finding_id,
            "first": {
                "person": first.as_dict(),
                "action": first_action,
                "status": first_status,
            },
            "second": {"person": person.as_dict(), "action": action, "status": status},
            "within_seconds": round(now - clash[0], 1),
        }

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
        with self._lock:
            return self._remember(
                self._room(content_id), finding_id, person, action, status
            )

    # --- from other processes --------------------------------------------------------

    def receive(self, message: dict[str, Any]) -> None:
        """A message another process sent. Our own, echoed back, is ignored."""
        if message.get("o") == self._origin:
            return
        kind = message.get("t")
        if kind == "event":
            self._receive_event(message)
        elif kind == "presence":
            self._receive_presence(message)
        elif kind == "focus":
            self._receive_focus(message)

    def _receive_event(self, message: dict[str, Any]) -> None:
        name, data = message["n"], message.get("d") or {}
        with self._lock:
            room = self._room(message["c"])
            # Ids rise within a room here, whatever the other process's clock said.
            self._append(room, Event(max(int(message["i"]), room.seq + 1), name, data))
            if name == "decision" and data.get("status") not in WAITING:
                actor = data.get("actor") or {}
                self._remember(
                    room,
                    data.get("finding_id", ""),
                    Person(
                        actor.get("id", ""),
                        actor.get("name", ""),
                        actor.get("role", ""),
                    ),
                    data.get("action", ""),
                    data.get("status", ""),
                )

    def _receive_focus(self, message: dict[str, Any]) -> None:
        """Someone's focus was posted to another process. If their stream is here, record it."""
        who = message.get("p") or {}
        share = None
        with self._lock:
            room = self._rooms.get(message["c"])
            viewer = room.viewers.get(who.get("id", "")) if room else None
            if viewer is not None and viewer.finding_id != message.get("f"):
                viewer.finding_id = message.get("f")
                self._publish(room, "presence", self._presence(room))
                share = self._share_presence(message["c"], room)
        if share:
            self._send(share)

    def _receive_presence(self, message: dict[str, Any]) -> None:
        with self._lock:
            room = self._room(message["c"])
            before = self._presence(room)
            if message.get("v"):
                room.remote[message["o"]] = (time.monotonic(), message["v"])
            else:
                room.remote.pop(message["o"], None)
            after = self._presence(room)
            if after != before:
                self._publish(room, "presence", after)

    def tick(self) -> None:
        """Called about once a second by the transport: resend our viewers, drop stale ones."""
        now = time.monotonic()
        heartbeat: list[dict[str, Any]] = []
        with self._lock:
            beat = now - self._last_heartbeat >= HEARTBEAT_S
            if beat:
                self._last_heartbeat = now
            for content_id, room in self._rooms.items():
                if beat and room.viewers:
                    heartbeat.append(self._share_presence(content_id, room))
                stale = [
                    o
                    for o, (seen, _) in room.remote.items()
                    if now - seen > PRESENCE_TTL_S
                ]
                if stale:
                    # What streams were last shown still counts the quiet process.
                    before = self._presence(room, fresh_only=False)
                    for origin in stale:
                        del room.remote[origin]
                    after = self._presence(room)
                    if after != before:
                        self._publish(room, "presence", after)
        self._send(*heartbeat)


hub = Hub()
