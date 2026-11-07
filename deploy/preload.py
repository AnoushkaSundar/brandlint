"""Gets a fresh deployment ready for judges: steps 1 and 2 of the demo, done for them.

It ingests and approves the guideline, adds the override history governance needs, and
uploads and reviews the three demo pieces, leaving them ready to resolve. Safe to run
again, inside the api container:

    docker compose exec api python /deploy/preload.py
"""

import sys
import time
import urllib.request
from pathlib import Path

import httpx

sys.path.insert(0, "/demo")
import seed_history

API = "http://localhost:8000"
PASSWORD = "brandlint-demo"
DEMO = Path("/demo")
PIECES = [
    ("Agency blog", "blog", "agency-blog.docx"),
    ("LinkedIn post", "linkedin", "linkedin-post.html"),
    ("Spring banner", "banner", "banner.png"),
]
# Must match FINAL_DRAFT in web/lib/demo.ts, which the tour looks for.
FINAL_DRAFT = "Agency blog, final draft"


def token(email: str) -> str:
    """Production cookies are HTTPS-only, and this talks to the API over the internal
    network, so it sends the session token as a header instead."""
    response = httpx.post(
        f"{API}/auth/login", json={"email": email, "password": PASSWORD}, timeout=60
    )
    response.raise_for_status()
    return response.json()["access_token"]


def login(email: str) -> httpx.Client:
    return httpx.Client(
        base_url=API, timeout=300, headers={"Authorization": f"Bearer {token(email)}"}
    )


class TokenClient(seed_history.Client):
    """seed_history's client, signed in by header rather than cookie."""

    def __init__(self, email: str):
        self.opener = urllib.request.build_opener()
        self.opener.addheaders = [("Authorization", f"Bearer {token(email)}")]


seed_history.Client = TokenClient


def wait_for(client: httpx.Client, engine_id: str) -> str:
    with client.stream("GET", f"/engine/reviews/{engine_id}/findings") as stream:
        event = None
        for line in stream.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
                if event in ("done", "error"):
                    return event
    return "ended"


def decide(client, content_id, finding_id, action, reason=None):
    return client.post(
        f"/workflow/content/{content_id}/findings/{finding_id}/decisions",
        json={"action": action, "reason": reason},
    )


def move(client, content_id, to):
    return client.post(
        f"/workflow/content/{content_id}/transitions",
        json={"to": to, "reason": "Ready for the demo."},
    )


def upload(creator, title, channel, name) -> tuple[str, str]:
    created = creator.post(
        "/content",
        data={"title": title, "channel": channel, "source": "agency", "data_class": "public"},
        files={"file": (name, (DEMO / "pieces" / name).read_bytes())},
    )
    created.raise_for_status()
    content_id = created.json()["id"]
    review = creator.post(f"/content/{content_id}/reviews")
    review.raise_for_status()
    started = time.time()
    ended = wait_for(creator, review.json()["engine_review_id"])
    moved = move(creator, content_id, "resolving").status_code
    print(f"  {title}: review {ended} in {time.time() - started:.0f}s, resolving={moved}")
    if ended != "done":
        raise SystemExit(f"{title}'s review didn't finish.")
    return content_id, review.json()["engine_review_id"]


def stage_for_manager(creator, reviewer, content_id) -> None:
    """Settles every finding, as a reviewer would, so the piece waits for the manager.
    The tour then shows a manager approving it and legal signing it off."""
    board = creator.get(f"/workflow/content/{content_id}/board").json()
    for finding in board["findings"]:
        if finding["status"] != "open":
            continue
        settled = decide(reviewer, content_id, finding["id"], "override", "Checked with the source.")
        if settled.status_code not in (200, 201):
            decide(reviewer, content_id, finding["id"], "resolve", "Checked for the demo.")
    for client, to in ((creator, "reviewer_check"), (reviewer, "manager_approval")):
        response = move(client, content_id, to)
        if response.status_code != 200:
            raise SystemExit(f"Couldn't move the final draft to {to}: {response.text[:160]}")
    print("  final draft: waiting for the manager")


def main() -> int:
    """Safe to run again: each part is skipped when it's already done."""
    admin = login("admin@tarnhollow.example")
    if admin.get("/admin/rulebook").status_code == 200:
        print("Rulebook already approved, skipping ingest.")
        return stage(admin)

    print("Ingesting the guideline…", flush=True)
    job = admin.post(
        "/admin/ingest",
        files={"file": ("guidelines.pdf", (DEMO / "brand/guidelines.pdf").read_bytes())},
    ).json()
    if job["status"] != "done":
        sys.exit(f"Ingest failed: {job['error']}")
    drafts = admin.get("/admin/rules/drafts").json()
    for pair in drafts["conflicts"]:
        loser = min(pair)
        admin.delete(f"/admin/rules/{loser}/draft").raise_for_status()
        print(f"  rejected {loser}, which contradicts {max(pair)}")
    ids = [rule["id"] for rule in admin.get("/admin/rules/drafts").json()["drafts"]]
    print("  approved:", admin.post("/admin/rules/approve", json={"rule_ids": ids}).json())

    print("Adding the override history…", flush=True)
    if seed_history.main() != 0:
        sys.exit("The override history failed.")
    return stage(admin)


def stage(admin: httpx.Client) -> int:
    creator = login("agency@tarnhollow.example")
    reviewer = login("reviewer@tarnhollow.example")
    have = {piece["title"] for piece in creator.get("/content").json()}
    for title, channel, name in PIECES:
        if title not in have:
            upload(creator, title, channel, name)
    if FINAL_DRAFT not in have:
        content_id, _ = upload(creator, FINAL_DRAFT, "blog", "agency-blog.docx")
        stage_for_manager(creator, reviewer, content_id)
    print("Ready for judges.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
