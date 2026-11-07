"""Demo history: earlier pieces whose tone finding a reviewer overrode.

The governance agent only proposes a rule change after a reviewer has confirmed at
least three overrides of the same judgment rule. A fresh demo has one, so this runs
four short pieces through the real workflow first: the real engine reviews each one,
and a reviewer overrides its R-TONE-02 finding with a reason. Nothing is written to
the database directly, and every piece is titled "Demo history" so it's clear what it is.

Run it after the rulebook is approved, against a running stack:

    docker compose exec api python /demo/seed_history.py

It uses only the standard library, and skips pieces that already exist.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar

API = os.environ.get("BRANDLINT_API", "http://localhost:8000")
PASSWORD = os.environ.get("DEMO_PASSWORD", "brandlint-demo")
RULE = "R-TONE-02"
REASON = "This states a real, documented risk plainly. It informs the reader; it isn't scaremongering."
PIECES = [
    (
        "Demo history: Payroll set-up",
        (
            "New hires should be added to payroll before their first day. Get it wrong and you "
            "may lose them before their second payday."
        ),
    ),
    (
        "Demo history: Welcome calls",
        (
            "A short welcome call in the first week helps managers spot problems early. Skip "
            "it, and you may only find out a new hire is struggling when their resignation lands."
        ),
    ),
    (
        "Demo history: Equipment checklist",
        (
            "Laptops and accounts should be ready before a new hire arrives. Every hour "
            "without access is an hour your new hire spends doubting you."
        ),
    ),
    # A spare, so one changed verdict doesn't leave the agent short of evidence.
    (
        "Demo history: Security training",
        (
            "Security training belongs in week one. One careless click from an untrained new "
            "hire can expose your whole company."
        ),
    ),
]


class Client:
    def __init__(self, email: str):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        self.request("POST", "/auth/login", {"email": email, "password": PASSWORD})

    def request(self, method: str, path: str, body=None, form=None):
        headers = {}
        data = None
        if form is not None:
            boundary = uuid.uuid4().hex
            parts = [
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                for key, value in form.items()
            ]
            data = ("".join(parts) + f"--{boundary}--\r\n").encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            API + path, data=data, method=method, headers=headers
        )
        try:
            with self.opener.open(request, timeout=300) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:200]
            raise SystemExit(
                f"{method} {path} failed with {error.code}: {detail}"
            ) from None
        return json.loads(raw) if raw else None

    def findings(self, engine_review_id: str) -> list[dict]:
        """Reads the findings stream to the end."""
        request = urllib.request.Request(
            f"{API}/engine/reviews/{engine_review_id}/findings"
        )
        found, event = [], None
        with self.opener.open(request, timeout=300) as stream:
            for raw in stream:
                line = raw.decode().strip()
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                    if event in ("done", "error"):
                        break
                elif line.startswith("data:") and event in (None, "finding"):
                    try:
                        found.append(json.loads(line[5:]))
                    except json.JSONDecodeError:
                        pass
        return found


def _has_confirmed_override(client: Client, content_id: str) -> bool:
    """Whether this piece's latest review has its tone finding overridden by a reviewer."""
    review = client.request("GET", f"/content/{content_id}").get("latest_review")
    if not review:
        return False
    tone = {
        finding["id"]
        for finding in client.findings(review["engine_review_id"])
        if finding.get("rule_id") == RULE
    }
    board = client.request("GET", f"/workflow/content/{content_id}/board")
    return any(
        item["id"] in tone and item["status"] == "override_confirmed"
        for item in board["findings"]
    )


def main() -> int:
    creator = Client("inhouse@tarnhollow.example")
    reviewer = Client("reviewer@tarnhollow.example")
    existing: dict[str, list[str]] = {}
    for item in creator.request("GET", "/content"):
        existing.setdefault(item["title"], []).append(item["id"])
    confirmed = 0
    for title, text in PIECES:
        if any(
            _has_confirmed_override(creator, cid) for cid in existing.get(title, [])
        ):
            print(f"skipped {title!r}: its override is already confirmed")
            confirmed += 1
            continue
        content = creator.request(
            "POST",
            "/content",
            form={
                "title": title,
                "channel": "blog",
                "source": "in-house",
                "data_class": "public",
                "text": text,
            },
        )
        review = creator.request("POST", f"/content/{content['id']}/reviews")
        findings = creator.findings(review["engine_review_id"])
        tone = [
            f
            for f in findings
            if f.get("rule_id") == RULE and f["verdict"] == "VIOLATION"
        ]
        if not tone:
            print(
                f"{title!r}: the model didn't flag {RULE}, so there's nothing to override"
            )
            continue
        creator.request(
            "POST",
            f"/workflow/content/{content['id']}/transitions",
            {"to": "resolving"},
        )
        decision = reviewer.request(
            "POST",
            f"/workflow/content/{content['id']}/findings/{tone[0]['id']}/decisions",
            {"action": "override", "reason": REASON},
        )
        print(f"{title!r}: {RULE} override {decision.get('status', 'saved')}")
        confirmed += 1
        time.sleep(0.2)
    print(f"{confirmed} of {len(PIECES)} pieces have a confirmed {RULE} override")
    return 0 if confirmed >= 3 else 1


if __name__ == "__main__":
    sys.exit(main())
