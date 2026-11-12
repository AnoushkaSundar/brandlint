"""Carries live-review messages between API processes, over Postgres LISTEN/NOTIFY.

Each process listens on one channel on a connection of its own, and sends by calling
`pg_notify`. Nothing is stored: a message reaches the processes that are listening at that
moment, which is all live updates need. A process that loses its listening connection
tells its open streams to reload (they may have missed something) and reconnects.

The messages carry no secrets beyond what a stream already shows, and the channel is only
reachable from inside our own database. Who may follow a piece is still decided by each
stream's own access check, never by what arrives here. On any database but Postgres there
is no bus, and the hub works alone.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any

from sqlalchemy import text

from app.collab.hub import Hub, hub
from app.db import get_engine

logger = logging.getLogger(__name__)

CHANNEL = "brandlint_collab"
# Postgres refuses a notification payload of 8000 bytes or more.
MAX_PAYLOAD = 7500
# Messages waiting to be sent. More than this and the oldest wait is a sign the database is down.
OUTBOX_SIZE = 1000


def _fit(message: dict[str, Any]) -> str:
    """The message as JSON that fits in a notification, shortening what it carries if needed."""
    payload = json.dumps(message, separators=(",", ":"))
    if len(payload.encode()) <= MAX_PAYLOAD:
        return payload
    data = message.get("d")
    if isinstance(data, dict):
        # The free text goes first: a reason can be long, and a stream shows it cut anyway.
        shortened = {k: (v[:200] if isinstance(v, str) else v) for k, v in data.items()}
        payload = json.dumps({**message, "d": shortened}, separators=(",", ":"))
        if len(payload.encode()) <= MAX_PAYLOAD:
            return payload
    return json.dumps({**message, "d": {}}, separators=(",", ":"))


class PgBus:
    def __init__(self, target: Hub) -> None:
        self._hub = target
        self._outbox: queue.Queue[str] = queue.Queue(maxsize=OUTBOX_SIZE)
        self.ready = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="collab-listen", daemon=True).start()
        threading.Thread(
            target=self._send_loop, name="collab-send", daemon=True
        ).start()

    def send(self, message: dict[str, Any]) -> None:
        """Queues a message for the other processes. Never waits on the database, so a slow
        or unreachable one can't hold up a decision. A full queue drops the message."""
        try:
            self._outbox.put_nowait(_fit(message))
        except queue.Full:
            logger.warning("live-review outbox is full, so a message was dropped")

    def _send_loop(self) -> None:
        while True:
            payload = self._outbox.get()
            try:
                with (
                    get_engine()
                    .connect()
                    .execution_options(isolation_level="AUTOCOMMIT") as connection
                ):
                    connection.execute(
                        text("SELECT pg_notify(:channel, :payload)"),
                        {"channel": CHANNEL, "payload": payload},
                    )
            except Exception:
                logger.warning("could not send a live-review message", exc_info=True)
                time.sleep(1.0)

    def _dsn(self) -> str:
        url = get_engine().url.set(drivername="postgresql")
        return url.render_as_string(hide_password=False)

    def _run(self) -> None:
        import psycopg

        backoff = 1.0
        connected_before = False
        while True:
            try:
                with psycopg.connect(self._dsn(), autocommit=True) as connection:
                    connection.execute(f"LISTEN {CHANNEL}")
                    if connected_before:
                        # Whatever was sent while we were away is gone: have streams reload.
                        self._hub.resync_all()
                    connected_before = True
                    backoff = 1.0
                    self.ready.set()
                    while True:
                        for notice in connection.notifies(timeout=1.0):
                            self._handle(notice.payload)
                        self._hub.tick()
            except Exception:
                logger.warning("live-review bus lost its connection", exc_info=True)
                self.ready.clear()
                time.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    def _handle(self, payload: str) -> None:
        try:
            self._hub.receive(json.loads(payload))
        except Exception:
            logger.warning("ignored a malformed live-review message", exc_info=True)


_started = False
_lock = threading.Lock()


def ensure_started(target: Hub = hub) -> None:
    """Joins the hub to the other processes, once per process. Safe to call on every request."""
    global _started
    if _started:
        return
    with _lock:
        if _started:
            return
        _started = True
        if get_engine().dialect.name != "postgresql":
            return
        bus = PgBus(target)
        target.attach(bus)
        bus.start()
