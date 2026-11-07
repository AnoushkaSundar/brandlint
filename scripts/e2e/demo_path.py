"""The demo script over HTTP, mocks off. Logs every problem and keeps going."""
import json
import pathlib
import sys
import time

import httpx

BASE = "http://localhost:8000"
PASSWORD = "brandlint-demo"
problems = []


def note(step, text):
    problems.append((step, text))
    print(f"  !! [{step}] {text[:230]}", flush=True)


class User:
    def __init__(self, role):
        self.role = role
        self.http = httpx.Client(base_url=BASE, timeout=200)
        r = self.http.post("/auth/login", json={"email": f"{role}@tarnhollow.example", "password": PASSWORD})
        if r.status_code != 200:
            sys.exit(f"login failed for {role}: {r.status_code} {r.text[:200]}")

    def go(self, step, method, url, ok=(200, 201), **kw):
        try:
            r = self.http.request(method, url, **kw)
        except Exception as exc:
            note(step, f"{self.role} {method} {url}: {type(exc).__name__} {exc}")
            return None
        if r.status_code not in ok:
            note(step, f"{self.role} {method} {url} -> {r.status_code}: {r.text[:170]}")
            return None
        return r.json() if r.content and "json" in r.headers.get("content-type", "") else r


creator, reviewer, manager, legal, admin = [
    User(r) for r in ("creator", "reviewer", "manager", "legal", "admin")
]


def stream(user, review_id):
    """Returns findings and seconds to the first one."""
    start, first, found = time.time(), None, []
    with user.http.stream("GET", f"/engine/reviews/{review_id}/findings", timeout=200) as r:
        if r.status_code != 200:
            note("stream", f"{r.status_code}")
            return [], None
        name = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:") and name == "finding":
                first = first or time.time() - start
                found.append(json.loads(line[5:]))
    return found, first


def upload(step, name, channel, data_class="public", text=None):
    data = {"title": name, "channel": channel, "source": "Agency", "data_class": data_class}
    files = None
    if text is None:
        files = {"file": (name, pathlib.Path(f"/demo/pieces/{name}").read_bytes())}
    else:
        data["text"] = text
    content = creator.go(step, "POST", "/content", data=data, files=files)
    if not content:
        return None, None
    review = creator.go(step, "POST", f"/content/{content['id']}/reviews")
    return content, review


def board(user, cid):
    return user.go("board", "GET", f"/workflow/content/{cid}/board")


print("== step 2/3: upload and review", flush=True)
pieces = {}
for name, channel in (("agency-blog.docx", "blog"), ("linkedin-post.html", "linkedin"), ("banner.png", "banner")):
    t = time.time()
    content, review = upload("review", name, channel)
    if not content or not review:
        continue
    print("  review keys", sorted(review)[:9]) if not pieces else None
    rid = review.get("engine_review_id") or review["id"]
    found, first = stream(creator, rid)
    print(f"  {name}: {len(found)} findings, first {first and round(first, 2)}s, total {time.time() - t:.1f}s", flush=True)
    if first and first > 1:
        note("latency", f"{name} first finding took {first:.2f}s")
    if not all(f["rule_id"] or f["fact_ids"] for f in found):
        note("citation", f"{name} has an uncited finding")
    pieces[name] = (content, rid, found)

print("== state after review", flush=True)
for name, (content, rid, found) in pieces.items():
    b = board(creator, content["id"])
    if b:
        print(f"  {name}: {b['state']} legal={b['legal_required']} moves={[(m['to'], (m['blocked_by'] or '')[:50]) for m in b['moves']]}", flush=True)

for name, (content, rid, found) in pieces.items():
    creator.go("resolving", "POST", f"/workflow/content/{content['id']}/transitions", json={"to": "resolving"})

if "agency-blog.docx" not in pieces:
    sys.exit("no blog")
blog, rid, found = pieces["agency-blog.docx"]
cid = blog["id"]

print("== step 3: trace, step 9: replay", flush=True)
same = total = 0
for f in found:
    if f["tier"] == 0:
        continue
    r = creator.go("replay", "POST", f"/engine/verdicts/{f['id']}/replay", ok=(200, 409))
    total += 1
    if r and r.get("identical"):
        same += 1
    elif r:
        note("replay", f"{f['rule_id']} not identical: {str(r)[:160]}")
print(f"  replay identical {same}/{total}", flush=True)

print("== step 5: fixes and overrides", flush=True)
b = board(creator, cid)
standing = {s["id"]: s for s in (b or {}).get("findings", [])}
fixes = 0
for f in found:
    allowed = standing.get(f["id"], {}).get("allowed", [])
    print(f"  {f['rule_id'] or '-':<12}{f['verdict']:<10}{f['severity']:<9} fix={f['fix_available']} allowed={allowed}", flush=True)
for f in found:
    if not f["fix_available"] or fixes >= 2:
        continue
    offer = creator.go("fix", "POST", f"/workflow/content/{cid}/findings/{f['id']}/fix", ok=(200, 201, 422), json={})
    if offer and offer.get("suggested"):
        print(f"  fix {offer['original'][:40]!r} -> {offer['suggested'][:50]!r}", flush=True)
        done = creator.go("fix", "POST", f"/workflow/content/{cid}/findings/{f['id']}/decisions", json={"action": "accept_fix", "attempt": offer.get("attempt")})
        fixes += 1 if done else 0
if fixes < 2:
    note("fix", f"only {fixes} fixes accepted")

low = next((f for f in found if f["severity"] == "low" and "override" in standing.get(f["id"], {}).get("allowed", [])), None)
if low:
    creator.go("override", "POST", f"/workflow/content/{cid}/findings/{low['id']}/decisions", json={"action": "override", "reason": "Used in a direct quote."})
    reviewer.go("override", "POST", f"/workflow/content/{cid}/findings/{low['id']}/decisions", json={"action": "confirm_override", "reason": "Fine in a quote."})
else:
    note("override", "no low finding the creator can override")

critical = next((f for f in pieces.get("linkedin-post.html", (0, 0, []))[2] if f["severity"] == "critical"), None)
if critical:
    lid = pieces["linkedin-post.html"][0]["id"]
    r = creator.http.post(f"/workflow/content/{lid}/findings/{critical['id']}/decisions", json={"action": "override", "reason": "No."})
    print(f"  step 4: creator override of critical -> {r.status_code}", flush=True)
    if r.status_code < 400:
        note("step4", "creator overrode a critical finding")

print("== step 6: resolve the rest and approve", flush=True)
q = reviewer.go("queue", "GET", "/workflow/queue")
print("  queue keys", list(q)[:6] if isinstance(q, dict) else type(q), flush=True)
for f in found:
    s = next((x for x in (board(reviewer, cid) or {"findings": []})["findings"] if x["id"] == f["id"]), None)
    if not s or s["status"] != "open":
        continue
    a = s["allowed"]
    action = "resolve" if "resolve" in a else None
    if action:
        reviewer.go("resolve", "POST", f"/workflow/content/{cid}/findings/{f['id']}/decisions", json={"action": action, "reason": "Checked."})
    else:
        c = next((x for x in board(creator, cid)["findings"] if x["id"] == f["id"]), {"allowed": []})
        if "override" in c["allowed"]:
            creator.go("resolve", "POST", f"/workflow/content/{cid}/findings/{f['id']}/decisions", json={"action": "override", "reason": "Accepted."})
            reviewer.go("resolve", "POST", f"/workflow/content/{cid}/findings/{f['id']}/decisions", json={"action": "confirm_override", "reason": "OK."})
        elif "override" in a:
            reviewer.go("resolve", "POST", f"/workflow/content/{cid}/findings/{f['id']}/decisions", json={"action": "override", "reason": "Reviewed."})
        else:
            note("resolve", f"nobody can clear {f['rule_id']} {f['verdict']} {s['status']} reviewer={a} creator={c['allowed']}")

for user in (creator, reviewer, manager, legal, reviewer, manager, legal):
    b = board(user, cid)
    if not b:
        break
    print(f"  {user.role}: {b['state']} moves={[(m['to'], (m['blocked_by'] or '')[:60]) for m in b['moves']]}", flush=True)
    forward = [m for m in b["moves"] if not m["blocked_by"] and m["to"] != "rejected" and m["to"] != "resolving"]
    if forward:
        user.go("move", "POST", f"/workflow/content/{cid}/transitions", json={"to": forward[0]["to"], "reason": "Looks right."})
b = board(admin, cid)
print("  final state", b and b["state"], flush=True)
if b and b["state"] != "published":
    note("publish", f"blog stuck in {b['state']}")
h = creator.go("history", "GET", f"/workflow/content/{cid}/history")
print("  history keys", list(h)[:6] if isinstance(h, dict) else None, flush=True)
admin.go("audit", "GET", "/workflow/audit")

print("== step 7: impact", flush=True)
for fact in ("F-002", "F-003"):
    print(f"  {fact}", (creator.go("impact", "GET", "/memory/impact", params={"fact_id": fact}) or [])[:3], flush=True)

print("== step 8: governance", flush=True)
print("  run", admin.go("governance", "POST", "/governance/run"), flush=True)
print("  spot", admin.go("governance", "GET", "/governance/spot-checks"), flush=True)
print("  creator run ->", creator.http.post("/governance/run").status_code, flush=True)

print("== step 9: trust", flush=True)
print("  disclosure", creator.go("trust", "GET", f"/gateway/reviews/{rid}/disclosure"), flush=True)
p = creator.go("trust", "GET", f"/gateway/reviews/{rid}/masking-preview")
print("  sent", p and p["sent"][:120], flush=True)
if p and "[PRODUCT_1]" not in p["sent"]:
    note("trust", "preview shows no token")

print("== step 10: graph", flush=True)
g = creator.go("graph", "GET", "/memory/graph", params={"root": "F-002"})
print("  graph", g and (len(g["nodes"]), len(g["edges"]), sorted({n["type"] for n in g["nodes"]})), flush=True)

print(f"\n=== {len(problems)} problems")
for step, text in problems:
    print(f"- [{step}] {text[:300]}")
