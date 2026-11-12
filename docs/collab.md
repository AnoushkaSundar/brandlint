# Live collaborative review

Several people can work on the same piece at once. They see who else is there, what the others just decided, and a warning when two people clash. **It only watches.** Every decision is still made and checked by the server, exactly as before. Nothing here can approve, fix or override anything.

## What a person sees

On the review screen, above the workflow bar:

- **Who is here:** "Lena · reviewer" for everyone else on the piece, and whether they have a finding open.
- **What just happened:** "Priya asked to override a finding.", "Lena confirmed an override.", "Marcus moved this to manager approval.", "Priya left a comment." Your own actions aren't announced back to you.
- **The board reloads by itself** when someone else changes it, so nobody decides on a stale screen.
- **Two people on one finding:** both are told "Someone else has this finding open too. Check what they decide before you do."
- **A clash:** if two different people each settle the same finding within 60 seconds (say one confirms an override and the other rejects it), both see who and how long apart, and are told to check before going on. A creator asking to override, and the reviewer's answer, is the normal flow and is never a clash.
- **A dropped connection catches up.** The browser reconnects by itself and asks for what it missed. If it missed too much, it reloads the board instead.

## API

| Call | Purpose |
|---|---|
| `GET /collab/content/{id}/events` (SSE) | the live stream for one piece |
| `GET /collab/content/{id}/presence` → `{viewers, contested}` | who is here now |
| `POST /collab/content/{id}/presence {finding_id}` → `{viewers, contested}` | which finding the caller is looking at. Counts only while their stream is open |

Anyone who may read the content may follow it, by the same rule as the content itself. Another creator, or another org once the tenancy blocks land, gets a 404.

Events (`id` rises per piece, so `Last-Event-ID` works):

| Event | Data |
|---|---|
| `hello` | `you`, `viewers`, `contested`, sent first |
| `presence` | `viewers`, `contested` |
| `decision` | `finding_id`, `actor`, `action`, `status`, `reason` |
| `state` | `from`, `to`, `actor`, `reason` |
| `comment` | `finding_id`, `actor`. **Not the text**, which is fetched as usual |
| `conflict` | `finding_id`, `first`, `second`, `within_seconds` |
| `resync` | the client was too far behind, so reload the board |

## How it works

- **No change to the workflow code.** A SQLAlchemy hook (`app/collab/publish.py`) notes the decisions, state changes and comments a request adds, and publishes them **after the commit**, so nobody hears about something that was rolled back. A failure there is logged and swallowed, and can't fail a decision.
- **A hub per process** (`app/collab/hub.py`) keeps the last 200 events for each piece, who is connected, and what each person is looking at. A slow browser that falls 200 events behind is told to resync instead of being sent half a history.
- **Several API processes share one live room** (`app/collab/bus.py`) through Postgres LISTEN/NOTIFY, with no new table. Each process applies an event at once and sends it on; the others apply it too, so a decision made on one reaches streams on any. Presence is shared as each process's own viewers, resent every 10 seconds and forgotten after 30 without a word, so a crashed process leaves no ghosts. A focus request that reaches a process other than the one holding the person's stream is forwarded to it. A process that loses its listening connection tells its open streams to reload. Sending never waits on the database. On a database without NOTIFY (SQLite) the hub just works alone.
- **A conflict is a heuristic.** Two different people each settling the same finding within 60 seconds. Only rulings count: a request that leaves the finding waiting for a reviewer doesn't. The hub can't know whether the second had seen the first, so it says what happened and leaves the call to them. The server's own checks still refuse an action that is no longer allowed.

## Limits

- **Messages aren't stored.** A message reaches the processes listening at that moment. A browser that reconnects to a process that held none of its events is told to reload the board, so nothing is lost, but missed events aren't replayed. A notification is capped at about 7.5 KB, so a very long reason is cut in what other processes see.
- **A conflict is announced by the process that records the second ruling.** It knows of the first from the bus, which is only as quick as a notification; two rulings landing in the same few milliseconds on two processes can each miss the other.
- **A restart empties the hub.** Browsers reconnect by themselves and reload the board, so nothing is lost, but missed events aren't replayed.
- **Presence is for whoever has a stream open.** Closing the tab leaves the room at once. A browser that vanishes without closing is dropped when the server notices the connection is gone.
- **Edits to the draft aren't live.** Only the review: decisions, state changes, comments and who is looking at what.
- **Proxies must not buffer.** The production Caddy file already turns buffering off for `/api`, and the stream sends an `X-Accel-Buffering: no` header for nginx.

## Tests

`api/tests/test_collab_processes.py`: two hubs joined by a wire (events, presence, a crashed process, forwarded focus, cross-process conflicts, a reconnect to a process that saw nothing) and, with `RLS_TEST_DATABASE_URL` set, the real Postgres bus. `demo/check_collab.py` runs it live: with `API2` set, the stream is followed on a second API process.

`api/tests/test_collab.py`: the hub (ordering, replay, resync, presence, conflicts, many threads at once), the stream, the commit hooks (a rolled-back decision publishes nothing, a failing hub never fails a decision), and who may follow. The tenancy harness (`api/tests/tenancy/routes.py`) calls every route, so it swaps an endless stream for a one-frame one: the real authorization still runs.
