"""Runs demo steps 1 to 10 against a running stack and reports what passed.

It does what the presenter does, through the API, as each role: ingest and approve
the guideline, upload and review the three pieces, add the demo history, resolve,
approve, edit a fact, run governance, check masking, the local route and Replay,
and read the graph. Start from an empty rulebook:

    docker compose exec api python -m app.admin.seed --without-rules
    docker compose exec api python /demo/check_demo.py

With every USE_MOCK_* flag off it calls the real model, so it costs a few cents. It
exits 1 if any check failed. It adds content, so reset the database before a demo.
"""

import json
import sys
import time
from pathlib import Path

import httpx
import seed_history

API = "http://localhost:8000"
PASSWORD = "brandlint-demo"
DEMO = Path(__file__).resolve().parent
problems: list[str] = []


def login(email: str) -> httpx.Client:
    client = httpx.Client(base_url=API, timeout=300)
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    response.raise_for_status()
    return client


def step(title: str) -> None:
    print(f"\n== {title}", flush=True)


def check(ok: bool, what: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)
    if not ok:
        problems.append(what)


admin = login("admin@tarnhollow.example")
step("1. Ingest the guideline")
started = time.time()
guideline = (DEMO / "brand/guidelines.pdf").read_bytes()
job = admin.post("/admin/ingest", files={"file": ("guidelines.pdf", guideline)}).json()
print(f"status={job['status']} error={job['error']} took={time.time() - started:.1f}s")
if job["status"] != "done":
    sys.exit("Ingest failed, so nothing else can run.")
drafts = admin.get("/admin/rules/drafts").json()
print(f"drafts={len(drafts['drafts'])} conflicts={drafts['conflicts']}")
print("ids:", [rule["id"] for rule in drafts["drafts"]])
print(
    "must_include with required_text:",
    {
        r["id"]: r.get("required_text")
        for r in drafts["drafts"]
        if r["type"] == "must_include"
    },
)

ids = [rule["id"] for rule in drafts["drafts"]]
refused = admin.post("/admin/rules/approve", json={"rule_ids": ids})
print("approve all ->", refused.status_code, refused.json().get("detail"))
for pair in drafts["conflicts"]:
    loser = min(pair)
    print("reject", loser, admin.delete(f"/admin/rules/{loser}/draft").status_code)
ids = [rule["id"] for rule in admin.get("/admin/rules/drafts").json()["drafts"]]
print(
    "approve rest ->", admin.post("/admin/rules/approve", json={"rule_ids": ids}).json()
)
print("rules in force:", len(admin.get("/admin/rulebook").json()))

step("2. Upload and review the three pieces")
creator = login("agency@tarnhollow.example")
pieces = [
    ("Agency blog", "blog", "agency-blog.docx"),
    ("LinkedIn post", "linkedin", "linkedin-post.html"),
    ("Spring banner", "banner", "banner.png"),
]
results = {}
for title, channel, name in pieces:
    data = (DEMO / "pieces" / name).read_bytes()
    created = creator.post(
        "/content",
        data={
            "title": title,
            "channel": channel,
            "source": "agency",
            "data_class": "public",
        },
        files={"file": (name, data)},
    )
    created.raise_for_status()
    content_id = created.json()["id"]
    review = creator.post(f"/content/{content_id}/reviews")
    print(f"{title}: content={content_id} review={review.status_code}")
    results[title] = {
        "content_id": content_id,
        "engine": review.json().get("engine_review_id"),
    }

for title, info in results.items():
    started = time.time()
    findings = []
    with creator.stream("GET", f"/engine/reviews/{info['engine']}/findings") as stream:
        event = None
        for line in stream.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event in (None, "finding"):
                payload = line.split(":", 1)[1].strip()
                if payload:
                    try:
                        findings.append(json.loads(payload))
                    except json.JSONDecodeError:
                        pass
            if event in ("done", "error"):
                print(f"  stream ended with {event}")
                break
    info["findings"] = findings
    print(f"\n{title}: {len(findings)} findings in {time.time() - started:.1f}s")
    for f in findings:
        print(
            f"  {f.get('severity', '?'):8} {f.get('verdict', '?'):9} {f.get('rule_id') or f.get('fact_ids')!s:18}"
            f" {f.get('check', '?'):14} {f.get('cited_text', '')[:60]!r}"
        )

step("Demo history for step 8")
if seed_history.main() != 0:
    check(False, "the demo history has fewer than three confirmed overrides")

creator = login("agency@tarnhollow.example")
reviewer = login("reviewer@tarnhollow.example")
manager = login("manager@tarnhollow.example")
legal = login("legal@tarnhollow.example")
admin = login("admin@tarnhollow.example")

blog = results["Agency blog"]
post = results["LinkedIn post"]


def board(client, content_id):
    return client.get(f"/workflow/content/{content_id}/board").json()


def decide(client, content_id, finding_id, action, reason=None, attempt=None):
    return client.post(
        f"/workflow/content/{content_id}/findings/{finding_id}/decisions",
        json={"action": action, "reason": reason, "attempt": attempt},
    )


def move(client, content_id, to, reason=None):
    return client.post(
        f"/workflow/content/{content_id}/transitions", json={"to": to, "reason": reason}
    )


check(
    any(
        f["verdict"] == "UNSURE" and f.get("rule_id") == "R-TONE-02"
        for f in blog["findings"]
    ),
    "the blog has the UNSURE tone item",
)
step("3. Findings cite and explain")
for title in ("Agency blog", "LinkedIn post", "Spring banner"):
    for finding in results[title]["findings"]:
        cited = bool(finding.get("rule_id") or finding.get("fact_ids"))
        traced = bool(finding.get("trace", {}).get("steps"))
        if not (cited and traced):
            check(False, f"{title} {finding['id']} cited={cited} traced={traced}")
check(True, "every finding cites a rule or fact and has a trace")

step("4. Hidden text can't be overridden by the creator")
hidden = next(f for f in post["findings"] if f["check"] == "hidden_content")
print("  board state:", board(creator, post["content_id"])["state"])
for to in ("resolving",):
    print("  move", to, move(creator, post["content_id"], to).status_code)
refused = decide(creator, post["content_id"], hidden["id"], "override", "It's fine")
check(
    refused.status_code in (403, 409, 422),
    f"creator override refused ({refused.status_code} {refused.json().get('detail')})",
)

step("5. Resolve the blog")
cid = blog["content_id"]
first = board(creator, cid)
print(
    "  state:",
    first["state"],
    "moves:",
    [(m["to"], m["blocked_by"]) for m in first["moves"]],
)
if first["state"] == "ai_review":
    print("  move resolving", move(creator, cid, "resolving").status_code)
fixed = 0
for finding in blog["findings"]:
    fid = finding["id"]
    if finding.get("fix_available") and fixed < 2:
        started = time.time()
        offer = creator.post(
            f"/workflow/content/{cid}/findings/{fid}/fix", json={"again": False}
        )
        if offer.status_code != 200:
            check(
                False,
                f"fix for {finding['rule_id']}: {offer.status_code} {offer.text[:120]}",
            )
            continue
        body = offer.json()
        print(
            f"  fix {finding.get('rule_id')}: {body['original'][:50]!r} -> {body['suggested'][:60]!r} ({time.time() - started:.1f}s)"
        )
        accepted = decide(creator, cid, fid, "accept_fix", attempt=body["attempt"])
        check(
            accepted.status_code in (200, 201),
            f"accept fix {finding.get('rule_id')} ({accepted.status_code})",
        )
        fixed += 1
fixed_ids = {f["id"] for f in blog["findings"] if f.get("fix_available")}
open_now = {f["id"] for f in board(creator, cid)["findings"] if f["status"] == "open"}
low = next(
    (
        f
        for f in blog["findings"]
        if f["severity"] in ("low", "medium")
        and f["id"] in open_now
        and f["verdict"] == "VIOLATION"
    ),
    None,
)
print("  candidate to override:", low and low["rule_id"])
if low:
    r = decide(creator, cid, low["id"], "override", "It's a direct customer quote.")
    check(
        r.status_code in (200, 201),
        f"creator overrides {low['rule_id']} ({r.status_code})",
    )
    r = decide(reviewer, cid, low["id"], "confirm_override")
    check(
        r.status_code in (200, 201), f"reviewer confirms the override ({r.status_code})"
    )
    precedents = reviewer.get("/memory/precedents", params={"finding_id": low["id"]})
    print(
        "  precedents:",
        precedents.status_code,
        len(precedents.json())
        if precedents.status_code == 200
        else precedents.text[:80],
    )

now = board(creator, cid)
standing = {f["id"]: f["status"] for f in now["findings"]}
for finding in blog["findings"]:
    if finding["verdict"] == "UNSURE" and standing.get(finding["id"]) == "open":
        r = decide(
            reviewer,
            cid,
            finding["id"],
            "resolve",
            "A factual risk, stated calmly. Fine.",
        )
        check(
            r.status_code in (200, 201),
            f"6. reviewer clears the UNSURE {finding['rule_id']} ({r.status_code})",
        )
        continue
    if standing.get(finding["id"]) == "open":
        r = decide(
            reviewer,
            cid,
            finding["id"],
            "override",
            "Checked with the source for the demo.",
        )
        print(
            f"  reviewer settles {finding.get('rule_id') or finding.get('fact_ids')} {finding['severity']}: {r.status_code} {r.json().get('detail', '') if r.status_code != 200 else ''}"
        )
        if r.status_code != 200:
            r = decide(reviewer, cid, finding["id"], "resolve", "Checked for the demo.")
            print(
                "    resolve:",
                r.status_code,
                r.json().get("detail", "") if r.status_code != 200 else "",
            )

step("6. Approve")
now = board(creator, cid)
print("  state:", now["state"], "legal_required:", now["legal_required"])
print("  moves:", [(m["to"], m["blocked_by"]) for m in now["moves"]])
for client, to in (
    (creator, "reviewer_check"),
    (reviewer, "manager_approval"),
    (manager, "legal_signoff"),
    (legal, "published"),
):
    r = move(client, cid, to, "Approved for the demo.")
    detail = "" if r.status_code == 200 else r.json().get("detail")
    check(r.status_code == 200, f"move to {to} ({r.status_code} {detail})")
    if r.status_code != 200:
        print(
            "  moves now:",
            [(m["to"], m["blocked_by"]) for m in board(client, cid)["moves"]],
        )
        break
history = manager.get(f"/workflow/content/{cid}/history").json()
print("  history keys:", list(history)[:6])
audit = admin.get("/workflow/audit", params={"limit": 5}).json()
check(audit.get("total", 0) > 0, f"audit log has {audit.get('total')} entries")

step("7. Impact")
facts = {f["id"]: f for f in admin.get("/admin/facts").json()}
fact = facts["F-002"]
body = {
    k: fact[k]
    for k in ("statement", "value", "source_doc", "owner", "valid_until", "data_class")
}
body["value"] = "41%"
body["statement"] = (
    fact["statement"].replace(fact["value"], "41%")
    if fact["value"] in fact["statement"]
    else fact["statement"] + " (updated)"
)
edited = admin.put("/admin/facts/F-002", json=body)
check(edited.status_code == 200, f"fact edit ({edited.status_code})")
impact = edited.json().get("impact", [])
print("  impact:", impact)
check(
    any(item["content_id"] == cid for item in impact), "the blog is in the impact list"
)
if impact:
    queued = admin.post(
        "/admin/facts/F-002/rereview",
        json={"content_ids": sorted({i["content_id"] for i in impact})},
    )
    check(
        queued.status_code == 200,
        f"re-review queued ({queued.status_code} {queued.json()})",
    )
    shown = creator.get(f"/content/{cid}").json().get("rereview")
    check(bool(shown), f"creator sees the request: {shown}")

step("8. Insights and governance")
signals = manager.get("/insights/signals").json()
print(
    "  override rates:",
    {
        k: v["rate"]
        for k, v in signals["override_rate_by_rule"].items()
        if v["overridden"]
    },
)
check(
    any(v["may_be_unclear"] for v in signals["override_rate_by_rule"].values()),
    "a rule is flagged as may be unclear",
)
started = time.time()
run = admin.post("/governance/run")
print(f"  governance run: {run.status_code} in {time.time() - started:.1f}s")
proposals = run.json() if run.status_code == 200 else []
check(
    bool(proposals),
    f"the agent proposed {[(p['rule_id'], p['eval']) for p in proposals]}",
)
if proposals:
    decided = admin.post(
        f"/governance/proposals/{proposals[0]['id']}", json={"status": "approved"}
    )
    drafts = admin.get("/admin/rules/drafts").json()["drafts"]
    check(
        decided.status_code == 200
        and any(d["id"] == proposals[0]["rule_id"] for d in drafts),
        "approved proposal is a draft rule",
    )
spot = reviewer.get("/governance/spot-checks")
print("  spot-checks:", spot.status_code, spot.text[:200])

step("9. Trust")
engine_id = blog["engine"]
disclosure = creator.get(f"/gateway/reviews/{engine_id}/disclosure")
print("  disclosure:", disclosure.status_code, disclosure.text[:300])
preview = creator.get(f"/gateway/reviews/{engine_id}/masking-preview")
print("  masking preview:", preview.status_code)
if preview.status_code == 200:
    sent = preview.json()["sent"]
    check("[PRODUCT_1]" in sent, "the codename was masked as [PRODUCT_1]")
    check("Bluewren" not in sent, "the codename never reached the model")
restricted = creator.post(
    "/content",
    data={
        "title": "Restricted note",
        "channel": "blog",
        "source": "agency",
        "data_class": "restricted",
        "text": "Our onboarding checklist helps every new hire settle in during the first week.",
    },
)
rid = restricted.json()["id"]
review = creator.post(f"/content/{rid}/reviews").json()
time.sleep(1)
deadline = time.time() + 240
while time.time() < deadline and board(creator, rid)["state"] == "ai_review":
    time.sleep(3)
local = creator.get(f"/gateway/reviews/{review['engine_review_id']}/disclosure")
print("  restricted disclosure:", local.status_code, local.text[:300])
check(
    local.status_code == 200 and "cloud" not in local.json().get("routes", []),
    "restricted piece never went to the cloud",
)
tier1 = next((f for f in post["findings"] if f.get("tier") == 1), None)
if tier1:
    replay = creator.post(f"/engine/verdicts/{tier1['id']}/replay")
    print("  replay:", replay.status_code, replay.text[:200])
    check(
        replay.status_code == 200 and replay.json().get("identical") is True,
        "Replay gives an identical result",
    )

step("10. Memory graph")
graph = admin.get("/memory/graph", params={"root": "F-002"})
nodes = graph.json().get("nodes", []) if graph.status_code == 200 else []
print("  graph:", graph.status_code, [(n["type"], n["label"][:30]) for n in nodes])
check(
    any(n["type"].lower() == "content" for n in nodes), "the graph reaches the content"
)

print("\nPROBLEMS:", problems or "none")
sys.exit(1 if problems else 0)
