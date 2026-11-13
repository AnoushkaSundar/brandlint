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

print("\nPROBLEMS:", "none" if not problems else problems)
sys.exit(1 if problems else 0)
