"""Two workspaces side by side on a running stack: neither can see the other.

It signs up two sandbox workspaces through the public API, has each create its own data,
and checks that nothing crosses. No model is called, so it costs nothing:

    MULTI_TENANT_SIGNUP=true on the API, then
    python demo/check_workspaces.py            # API defaults to http://localhost:8000

Each run creates two workspaces that expire by themselves. Signup is rate limited per
address (5 an hour by default), so a run uses two of those. Exits 1 if any check failed.
"""

import os
import sys
import uuid

import httpx

API = os.environ.get("API", "http://localhost:8000")
PASSWORD = "check-password-123"
problems: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)
    if not ok:
        problems.append(what)


def client() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=60)


def signup(tag: str) -> httpx.Client:
    session = client()
    response = session.post(
        "/orgs",
        json={
            "workspace_name": f"Check {tag}",
            "name": f"Admin {tag}",
            "email": f"{tag}-{uuid.uuid4().hex[:8]}@check.example",
            "password": PASSWORD,
        },
    )
    response.raise_for_status()
    return session


def sign_in(email: str) -> httpx.Client:
    session = client()
    session.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    ).raise_for_status()
    return session


print("== Two workspaces")
a, b = signup("a"), signup("b")
wa, wb = a.get("/orgs/current").json(), b.get("/orgs/current").json()
check(wa["id"] != wb["id"], "each signup made its own workspace")
check(
    wa["kind"] == "sandbox" and wa["expires_at"] is not None,
    "a sandbox, with an expiry",
)
check(
    not any(wa["checklist"].values()),
    "it starts empty: nothing on the checklist is done",
)

print("== Their own data")
a.post(
    "/admin/terms", json={"preferred": "Alpha-only term", "banned": ["alpha-ban"]}
).raise_for_status()
b.post(
    "/admin/terms", json={"preferred": "Beta-only term", "banned": ["beta-ban"]}
).raise_for_status()
terms_a = {t["preferred"] for t in a.get("/admin/terms").json()}
terms_b = {t["preferred"] for t in b.get("/admin/terms").json()}
check(terms_a == {"Alpha-only term"}, "A sees only its own term")
check(terms_b == {"Beta-only term"}, "B sees only its own term")
check(len(a.get("/admin/users").json()) == 1, "A's people are only A's")

print("== Content")
a.post(
    "/admin/users",
    json={
        "email": f"creator-{uuid.uuid4().hex[:8]}@check.example",
        "name": "Cleo",
        "role": "creator",
        "password": PASSWORD,
    },
).raise_for_status()
creator_email = next(
    u["email"] for u in a.get("/admin/users").json() if u["role"] == "creator"
)
creator = sign_in(creator_email)
made = creator.post(
    "/content",
    data={
        "title": "A's draft",
        "channel": "blog",
        "source": "in-house",
        "data_class": "public",
        "text": "Hello from A.",
    },
)
check(made.status_code == 201, "A's creator can add a draft")
content_id = made.json()["id"]
check(
    b.get(f"/content/{content_id}").status_code == 404,
    "B can't open A's draft by its id (404)",
)
check(
    content_id not in {c["id"] for c in b.get("/content").json()},
    "B's list doesn't include it",
)

print("== A new workspace has no rules")
blocked = creator.post(f"/content/{content_id}/reviews")
check(
    blocked.status_code == 409 and "no approved rules" in blocked.text,
    "a review in an empty workspace is refused with a reason",
)
check(
    a.get("/admin/rulebook").status_code == 404,
    "its rulebook is empty, not a silent pass",
)

print("== Sample guidelines go to one workspace only")
a.post("/admin/sample-guidelines").raise_for_status()
check(a.get("/admin/rulebook").status_code == 200, "A now has the sample rules")
check(b.get("/admin/rulebook").status_code == 404, "B still has none")
check(
    a.get("/orgs/current").json()["checklist"]["approved_rules"],
    "A's checklist shows rules approved",
)

print("== Only the demo can be reset")
check(
    a.post("/admin/demo/reset").status_code == 403,
    "a sandbox admin can't reset the demo",
)

print("\nPROBLEMS:", "none" if not problems else problems)
sys.exit(1 if problems else 0)
