"""Live review on a running stack: people in one workspace see each other and each other's
decisions as they happen, and another workspace sees none of it. No model is called.

    MULTI_TENANT_SIGNUP=true on the API, then
    python demo/check_collab.py
    API2=http://localhost:8001 python demo/check_collab.py   # a second API process

With API2 set, the stream is followed on the second process while everything happens on the
first, which proves events and presence cross processes (both must use the same database).
The API must run with the mock engine (the default), so a review has findings without a model.
Exits 1 if any check failed.
"""

import os
import sys
import threading
import time
import uuid

import httpx

API = os.environ.get("API", "http://localhost:8000")
API2 = os.environ.get("API2", API)
PASSWORD = "check-password-123"
problems: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)
    if not ok:
        problems.append(what)


def client(base: str = API) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=60)


def signup(tag: str) -> httpx.Client:
    session = client()
    session.post(
        "/orgs",
        json={
            "workspace_name": f"Collab {tag}",
            "name": f"Admin {tag}",
            "email": f"{tag}-{uuid.uuid4().hex[:8]}@check.example",
            "password": PASSWORD,
        },
    ).raise_for_status()
    return session


def person(admin: httpx.Client, role: str, name: str) -> httpx.Client:
    email = f"{role}-{uuid.uuid4().hex[:8]}@check.example"
    admin.post(
        "/admin/users",
        json={"email": email, "name": name, "role": role, "password": PASSWORD},
    ).raise_for_status()
    session = client()
    session.post("/auth/login", json={"email": email, "password": PASSWORD}).raise_for_status()
    return session


class Stream:
    """Follows a piece's live events on one API process until closed."""

    def __init__(self, base: str, who: httpx.Client, content_id: str) -> None:
        self.lines: list[str] = []
        self.status: int | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(base, who, content_id), daemon=True)
        self._thread.start()

    def _run(self, base: str, who: httpx.Client, content_id: str) -> None:
        try:
            with httpx.Client(base_url=base, timeout=None, cookies=who.cookies) as c:
                with c.stream("GET", f"/collab/content/{content_id}/events") as r:
                    self.status = r.status_code
                    for line in r.iter_lines():
                        self.lines.append(line)
                        if self._stop.is_set():
                            break
        except httpx.HTTPError:
            pass  # closed on purpose, or the server went away

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def close(self) -> None:
        self._stop.set()


print(f"== A workspace with an admin, a creator and two reviewers ({API}, followed on {API2})")
a = signup("a")
a.post("/admin/sample-guidelines").raise_for_status()
creator = person(a, "creator", "Priya")
lena = person(a, "reviewer", "Lena")
marcus = person(a, "reviewer", "Marcus")

made = creator.post(
    "/content",
    data={
        "title": "Live piece",
        "channel": "blog",
        "source": "agency",
        "data_class": "public",
        "text": "Hello from A.",
    },
)
made.raise_for_status()
cid = made.json()["id"]
creator.post(f"/content/{cid}/reviews").raise_for_status()
time.sleep(2)

print("== Lena follows on one process, Marcus on the other")
lena_stream = Stream(API2, lena, cid)
marcus_stream = Stream(API, marcus, cid)
time.sleep(2.5)
presence = lena.get(f"/collab/content/{cid}/presence").json()
names = {v["name"] for v in presence["viewers"]}
check({"Lena", "Marcus"} <= names, f"presence shows both reviewers (saw {sorted(names)})")

print("== Two reviewers on the same finding")
board_finding = "fnd-agency-blog-01"
lena.post(f"/collab/content/{cid}/presence", json={"finding_id": board_finding}).raise_for_status()
marcus.post(f"/collab/content/{cid}/presence", json={"finding_id": board_finding}).raise_for_status()
time.sleep(1.5)
for label, who in (("Lena", lena), ("Marcus", marcus)):
    seen = who.get(f"/collab/content/{cid}/presence").json()
    check(seen["contested"] == [board_finding], f"{label} is told two people are on {board_finding}")
check('"contested":["fnd-agency-blog-01"]' in lena_stream.text.replace(" ", ""), "Lena's stream carried the flag")

print("== Priya decides")
mv = creator.post(f"/workflow/content/{cid}/transitions", json={"to": "resolving"})
check(mv.status_code in (200, 201), f"Priya moves the piece on to resolving ({mv.status_code})")
board = creator.get(f"/workflow/content/{cid}/board").json()
target = next((f["id"] for f in board["findings"] if "override" in f["allowed"]), None)
check(target is not None, "there is a finding Priya can override")
r = creator.post(
    f"/workflow/content/{cid}/findings/{target}/decisions",
    json={"action": "override", "reason": "A direct customer quote."},
)
check(r.status_code == 201, "Priya's override is accepted")
time.sleep(3)
for label, stream in (("Lena (other process)", lena_stream), ("Marcus", marcus_stream)):
    check(stream.status == 200, f"{label}'s stream opened")
    check("event: state" in stream.text, f"{label} saw the piece change state live")
    check("event: decision" in stream.text and "Priya" in stream.text, f"{label} saw Priya's decision live")

print("== Leaving")
marcus_stream.close()
lena_stream.close()

print("== Another workspace sees nothing")
b = signup("b")
check(b.get(f"/collab/content/{cid}/presence").status_code == 404, "B can't read A's presence (404)")
check(
    b.post(f"/collab/content/{cid}/presence", json={"finding_id": board_finding}).status_code == 404,
    "B can't say it is looking at A's finding (404)",
)
with client(API2).stream("GET", f"/collab/content/{cid}/events", cookies=b.cookies) as r:
    check(r.status_code == 404, "B can't follow A's stream (404)")
check(client().get(f"/collab/content/{cid}/presence").status_code == 401, "nobody signed out can read presence")

print("\nPROBLEMS:", "none" if not problems else problems)
sys.exit(1 if problems else 0)
