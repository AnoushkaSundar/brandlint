"""Steps the first run couldn't reach. Argument picks a stage, so outages can run between."""
import json
import sys
import threading
import time

import httpx

BASE = "http://localhost:8000"
bad = []


def note(area, text):
    bad.append((area, text))
    print(f"  !! [{area}] {text[:220]}", flush=True)


def login(role):
    c = httpx.Client(base_url=BASE, timeout=150)
    r = c.post("/auth/login", json={"email": f"{role}@tarnhollow.example", "password": "brandlint-demo"})
    assert r.status_code == 200, r.text
    return c


creator, agency, reviewer, manager, admin = [login(r) for r in ("creator", "agency", "reviewer", "manager", "admin")]


def finish(client, rid):
    found, end = [], None
    with client.stream("GET", f"/engine/reviews/{rid}/findings", timeout=150) as r:
        if r.status_code != 200:
            return [], f"http {r.status_code}"
        name = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                if name == "finding":
                    found.append(json.loads(line[5:]))
                else:
                    end = name
    return found, end


def submit(title, text, data_class="public", client=creator):
    r = client.post("/content", data={"title": title, "channel": "blog", "source": "Agency", "data_class": data_class, "text": text})
    if r.status_code != 201:
        note("submit", f"{title} {r.status_code} {r.text[:120]}")
        return None, None
    cid = r.json()["id"]
    r = client.post(f"/content/{cid}/reviews")
    if r.status_code != 201:
        note("submit", f"review {title} {r.status_code} {r.text[:120]}")
        return cid, None
    return cid, r.json()["engine_review_id"]


def resolving(cid, client=creator):
    return client.post(f"/workflow/content/{cid}/transitions", json={"to": "resolving"}).status_code


def board(cid, client=creator):
    return client.get(f"/workflow/content/{cid}/board").json()


stage = sys.argv[1]

if stage == "memory":
    print("== extraction no longer fails on claim-free text", flush=True)
    stamp = str(time.time())[-5:]
    cid, rid = submit("clean", f"The welcome pack {stamp} is on your desk.")
    found, end = finish(creator, rid)
    print(f"  end={end} findings={[(f['rule_id'], f['verdict'], f['explanation'][:44]) for f in found]}", flush=True)
    if any("couldn't be extracted" in f["explanation"] for f in found):
        note("extract", "still failing on claim-free text")

    print("== access after the fix", flush=True)
    cid, rid = submit("private", "Secret plan: Bluewren launches in March.")
    found, _ = finish(creator, rid)
    for label, url in (("preview", f"/gateway/reviews/{rid}/masking-preview"), ("disclosure", f"/gateway/reviews/{rid}/disclosure"),
                       ("findings", f"/engine/reviews/{rid}/findings"), ("chunks", f"/engine/reviews/{rid}/chunks"),
                       ("impact", "/memory/impact?fact_id=F-002"), ("graph", f"/memory/graph?root={cid}"), ("spot", "/governance/spot-checks")):
        code = agency.get(url).status_code
        own = creator.get(url).status_code
        staff = reviewer.get(url).status_code
        print(f"  {label:<11} other creator {code}  owner {own}  reviewer {staff}", flush=True)
        if code == 200:
            note("access", f"other creator can read {label}")
        if staff != 200:
            note("access", f"reviewer refused {label}")
    if found:
        print("  replay other creator", agency.post(f"/engine/verdicts/{found[0]['id']}/replay").status_code, flush=True)

    print("== six fix requests at once", flush=True)
    cid, rid = submit("fixes", f"Our best-in-class team {stamp} welcomes you.")
    found, _ = finish(creator, rid)
    resolving(cid)
    f = next((x for x in found if x["fix_available"]), None)
    if f:
        out = []
        ts = [threading.Thread(target=lambda: out.append(login("creator").post(f"/workflow/content/{cid}/findings/{f['id']}/fix", json={"again": True}).status_code)) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        print("  statuses", sorted(out), flush=True)
        if any(c >= 500 for c in out):
            note("fix", f"parallel fix {out}")
    else:
        note("fix", "no fixable finding to race")

    print("== a confirmed override becomes a precedent", flush=True)
    term = "The newbies settled in on day {}."
    first, rid1 = submit("prec1", term.format(stamp))
    f1, _ = finish(creator, rid1)
    resolving(first)
    low = next((x for x in f1 if x["rule_id"] == "R-TERM-03"), None)
    if low:
        u = f"/workflow/content/{first}/findings/{low['id']}/decisions"
        print("  override", creator.post(u, json={"action": "override", "reason": "A direct quote."}).status_code,
              "confirm", reviewer.post(u, json={"action": "confirm_override", "reason": "Fine in a quote."}).status_code, flush=True)
    second, rid2 = submit("prec2", term.format(stamp + "x"))
    f2, _ = finish(creator, rid2)
    low2 = next((x for x in f2 if x["rule_id"] == "R-TERM-03"), None)
    if low2:
        p = creator.get("/memory/precedents", params={"finding_id": low2["id"]})
        print("  precedents", p.status_code, p.text[:200], flush=True)
        if not p.json():
            note("precedent", "no precedent came back")

if stage == "governance":
    print("== step 8 through the workflow: confirmed overrides on one rule", flush=True)
    made = 0
    for n in range(4):
        stamp = str(time.time())[-6:]
        cid, rid = submit(f"gov{n}", f"If you ignore the risk {stamp}, your best people may leave.")
        found, _ = finish(creator, rid)
        resolving(cid)
        f = next((x for x in found if x["rule_id"] and x["rule_id"].startswith("R-TONE") and x["verdict"] == "VIOLATION"), None)
        if not f:
            print(f"  {n}: tone rule didn't fire: {[(x['rule_id'], x['verdict']) for x in found]}", flush=True)
            continue
        u = f"/workflow/content/{cid}/findings/{f['id']}/decisions"
        a = creator.post(u, json={"action": "override", "reason": "This states a real risk factually."}).status_code
        b = reviewer.post(u, json={"action": "confirm_override", "reason": "Factual, not pressure."}).status_code
        print(f"  {n}: {f['rule_id']} override {a} confirm {b}", flush=True)
        made += a < 300 and b < 300
    t = time.time()
    r = admin.post("/governance/run")
    print(f"  run {r.status_code} {time.time() - t:.1f}s", flush=True)
    proposals = r.json() if r.status_code == 200 else []
    for p in proposals:
        print(f"  {p['rule_id']} {p['status']} eval={p['eval']} evidence={p['evidence']['count']}\n    {p['suggested'][:150]}", flush=True)
    if made >= 3 and not proposals:
        note("governance", "enough overrides but no proposal")
    if proposals:
        pid = proposals[0]["id"]
        print("  reviewer tries to approve", reviewer.post(f"/governance/proposals/{pid}", json={"status": "approved"}).status_code, flush=True)
        print("  admin approves", admin.post(f"/governance/proposals/{pid}", json={"status": "approved"}).status_code, flush=True)
        print("  admin approves twice", admin.post(f"/governance/proposals/{pid}", json={"status": "approved"}).status_code, flush=True)
    print("  second run stays quiet", admin.post("/governance/run").json(), flush=True)

if stage == "outage":
    print("== review during the outage named in the argument", sys.argv[2], flush=True)
    stamp = str(time.time())[-6:]
    t = time.time()
    data_class = "internal" if sys.argv[2] == "presidio" else "public"
    cid, rid = submit("outage", f"Maria Lopez says the newbies {stamp} loved the best-in-class tour.", data_class)
    found, end = finish(creator, rid)
    print(f"  end={end} {time.time() - t:.1f}s findings={[(f['rule_id'], f['verdict'], f['tier']) for f in found]}", flush=True)
    b = board(cid)
    print(f"  state={b['state']} moves={[(m['to'], (m['blocked_by'] or '')[:40]) for m in b['moves']]}", flush=True)
    if not any(f["tier"] == 0 for f in found):
        note("outage", "code findings were lost")
    if end == "done" and not any(f["verdict"] == "UNSURE" for f in found):
        note("outage", "AI checks passed silently during an outage")

if stage == "restart":
    print("== restart while a review runs, part 1", flush=True)
    cid, rid = submit("restart", "Long enough text to keep the model busy. " + " ".join(f"Paragraph {i} says newbies love it." for i in range(30)))
    print(json.dumps({"cid": cid, "rid": rid}), flush=True)

if stage == "after-restart":
    cid, rid = sys.argv[2], sys.argv[3]
    b = creator.get(f"/workflow/content/{cid}/board")
    print("  board", b.status_code, b.text[:230], flush=True)
    r = creator.get(f"/engine/reviews/{rid}/findings", timeout=20)
    print("  stream", r.status_code, r.text[:120].replace("\n", " "), flush=True)
    print("  restart review", creator.post(f"/content/{cid}/reviews").status_code, flush=True)

print(f"=== {len(bad)} problems")
for area, text in bad:
    print(f"- [{area}] {text}")
