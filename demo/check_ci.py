"""The CI/CD integration on a running stack, end to end. No model is called.

    CI_INTEGRATION_ENABLED=true and MULTI_TENANT_SIGNUP=true on the API (mock engine), then
    python demo/check_ci.py                      # API defaults to http://localhost:8000

It makes two workspaces and works as a CI job would: service tokens, runs, the server's
verdict, and a waiver. Exits 1 if any check failed. See docs/ci-integration.md.
"""

import sys
import uuid

import httpx

API = "http://localhost:8000"
PASSWORD = "check-password-123"
problems: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)
    if not ok:
        problems.append(what)


def client(headers: dict | None = None) -> httpx.Client:
    return httpx.Client(base_url=API, timeout=60, headers=headers or {})


def signup(tag: str) -> httpx.Client:
    session = client()
    session.post(
        "/orgs",
        json={
            "workspace_name": f"CI {tag}",
            "name": f"Admin {tag}",
            "email": f"{tag}-{uuid.uuid4().hex[:8]}@check.example",
            "password": PASSWORD,
        },
    ).raise_for_status()
    return session


print("== Service tokens")
a, b = signup("a"), signup("b")
made = a.post("/ci/tokens", json={"name": "GitHub Action"})
check(made.status_code == 201 and made.json()["token"].startswith("bl_"), "an admin makes a token, shown once")
token = made.json()["token"]
listed = a.get("/ci/tokens").json()
check(all("token" not in row and "token_hash" not in row for row in listed), "the list shows only the prefix")
bot = client({"Authorization": f"Bearer {token}"})
check(bot.get("/ci/whoami").json().get("kind") == "token", "the token works on /ci routes")
for path in ("/content", "/admin/rulebook", "/workflow/queue"):
    check(bot.get(path).status_code == 401, f"the token is refused on {path}")
check(b.delete(f"/ci/tokens/{made.json()['id']}").status_code == 404, "another workspace can't revoke it (404)")
check(a.delete(f"/ci/tokens/{made.json()['id']}").status_code == 204, "its own admin can revoke it")
check(bot.get("/ci/whoami").status_code == 401, "a revoked token stops working at once")

print("== A run")
a2, b2 = signup("a2"), signup("b2")
a2.post("/admin/sample-guidelines").raise_for_status()  # a workspace needs approved rules
token2 = a2.post("/ci/tokens", json={"name": "CI"}).json()["token"]
bot2 = client({"Authorization": f"Bearer {token2}"})
body = {
    "repo": "acme/site",
    "pr": 7,
    "sha": "abc123",
    "files": [
        {"path": "docs/clean.md", "channel": "blog", "text": "Tarnhollow Landing helps teams onboard."},
        {"path": "docs/violating.md", "channel": "blog", "text": "Tarnhollow Onramp is best-in-class."},
    ],
}
created = bot2.post("/ci/runs", json=body)
check(created.status_code == 201, f"a token sends files and gets a run ({created.status_code})")
run_id = created.json()["id"]
status = bot2.get(f"/ci/runs/{run_id}").json()
check(status["state"] == "done" and len(status["files"]) == 2, "the run finishes with a result per file")
check(any(f["findings"] for f in status["files"]), "findings come back with links")
again = bot2.post("/ci/runs", json=body)
check(again.status_code == 200 and again.json()["id"] == run_id, "the same files again return the same run")
for bad in ("../x.md", "/etc/passwd", "a\\b.md"):
    refused = bot2.post(
        "/ci/runs",
        json={**body, "sha": "z", "files": [{"path": bad, "channel": "blog", "text": "Hi."}]},
    )
    check(refused.status_code == 422, f"the path {bad!r} is refused")
check(b2.get(f"/ci/runs/{run_id}").status_code == 404, "another workspace can't read the run (404)")
creator_email = f"cr-{uuid.uuid4().hex[:8]}@check.example"
a2.post(
    "/admin/users",
    json={"email": creator_email, "name": "Cleo", "role": "creator", "password": PASSWORD},
).raise_for_status()
cleo = client()
cleo.post("/auth/login", json={"email": creator_email, "password": PASSWORD}).raise_for_status()
check(all(row["source"] != "ci" for row in cleo.get("/content").json()), "CI content is not in a creator's list")
check(len(a2.get("/admin/users").json()) == 2, "the CI service user isn't listed as a person")

print("\nPROBLEMS:", "none" if not problems else problems)
sys.exit(1 if problems else 0)
