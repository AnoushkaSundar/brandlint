"""The mocks are what the review screen is built against, so they have to behave like
the contract in docs/contracts.md and the behaviour table in the build brief.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import app.gateway
import pytest
from app.auth.dependencies import current_user
from app.clients import engine as engine_client
from app.clients import gateway as gateway_client
from app.clients.router import build_router
from app.clients.router import router as clients_router
from app.db import get_session
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mocks import data, engine, gateway, governance, memory

DEMO = Path(__file__).resolve().parents[2] / "demo"
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="demo/ is not available")


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setenv("MOCK_STREAM_DELAY", "0")
    engine.reset()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(clients_router)
    app.dependency_overrides[current_user] = lambda: object()
    return TestClient(app)


def parse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def stream(client, piece):
    response = client.get(f"/engine/reviews/rev-demo-{piece}/findings")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_events(response.text)


def test_mock_routes_need_a_session():
    app = FastAPI()
    app.include_router(clients_router)
    app.dependency_overrides[get_session] = lambda: None

    assert TestClient(app).get("/memory/impact?fact_id=F-002").status_code == 401


@pytest.mark.parametrize(
    ("channel", "piece"),
    [
        ("blog", "agency-blog"),
        ("linkedin", "linkedin-post"),
        ("banner", "banner"),
        ("email", "agency-blog"),
    ],
)
def test_starting_a_review_picks_a_piece_by_channel(client, channel, piece):
    response = client.post(
        "/engine/reviews",
        json={
            "content_version_id": "cv-1",
            "channel": channel,
            "rulebook_version": 1,
        },
    )

    assert response.json() == {"review_id": f"rev-demo-{piece}"}


@pytest.mark.parametrize("piece", data.PIECES)
def test_the_stream_sends_every_finding_then_done(client, piece):
    events = stream(client, piece)
    expected = {finding["id"] for finding in data.findings_for_piece(piece)}

    assert {payload["id"] for name, payload in events[:-1]} == expected
    assert all(name == "finding" for name, _ in events[:-1])
    assert events[-1] == ("done", {"count": len(expected)})


@pytest.mark.parametrize("piece", data.PIECES)
def test_code_findings_arrive_first(client, piece):
    tiers = [payload["tier"] for name, payload in stream(client, piece) if name == "finding"]

    assert tiers == sorted(tiers)


def test_only_ai_findings_wait(monkeypatch):
    sent = []

    async def record_sleep(_):
        sent.append("sleep")

    monkeypatch.setattr(engine.asyncio, "sleep", record_sleep)
    findings = data.findings_for_piece("agency-blog")

    async def collect():
        async for event in engine._stream(findings):
            sent.append(event.split("\n")[0])

    asyncio.run(collect())

    tier_zero = sum(finding["tier"] == 0 for finding in findings)
    assert sent[:tier_zero] == ["event: finding"] * tier_zero
    assert sent.count("sleep") == len(findings) - tier_zero


def test_an_unknown_review_is_not_found(client):
    assert client.get("/engine/reviews/nope/findings").status_code == 404


def test_recheck_only_sends_findings_in_changed_chunks(client):
    response = client.post(
        "/engine/reviews/rev-demo-agency-blog/recheck",
        json={"changed_chunk_ids": ["blog-p2"]},
    )

    events = parse_events(response.text)
    found = [payload for name, payload in events if name == "finding"]
    assert [finding["id"] for finding in found] == [
        "fnd-agency-blog-01",
        "fnd-agency-blog-02",
    ]


def test_a_recheck_with_nothing_relevant_sends_only_done(client):
    response = client.post(
        "/engine/reviews/rev-demo-agency-blog/recheck",
        json={"changed_chunk_ids": ["blog-p7"]},
    )

    assert parse_events(response.text) == [("done", {"count": 0})]


def test_a_fix_returns_the_contract_shape(client):
    response = client.post("/engine/findings/fnd-agency-blog-01/fix")

    assert response.json() == {
        "finding_id": "fnd-agency-blog-01",
        "original": "Tarnhollow Onramp",
        "suggested": "Tarnhollow Landing",
        "diff": "- Tarnhollow Onramp\n+ Tarnhollow Landing",
        "attempt": 1,
    }


def test_the_third_fix_attempt_fails(client):
    url = "/engine/findings/fnd-agency-blog-01/fix"

    assert client.post(url).json()["attempt"] == 1
    assert client.post(url).json()["attempt"] == 2

    third = client.post(url)
    assert third.status_code == 422
    assert third.json()["detail"] == "No safe fix found; marked for review"


def test_fix_attempts_are_counted_per_finding(client):
    for _ in range(3):
        client.post("/engine/findings/fnd-agency-blog-01/fix")

    response = client.post("/engine/findings/fnd-agency-blog-02/fix")

    assert response.json()["attempt"] == 1


def test_a_finding_without_a_fix_says_so(client):
    assert client.post("/engine/findings/fnd-agency-blog-04/fix").status_code == 409


def test_an_unknown_finding_is_not_found(client):
    assert client.post("/engine/findings/nope/fix").status_code == 404
    assert client.post("/engine/verdicts/nope/replay").status_code == 404


@pytest.mark.parametrize("piece", data.PIECES)
def test_every_offered_fix_has_canned_text(client, piece):
    for finding in data.findings_for_piece(piece):
        response = client.post(f"/engine/findings/{finding['id']}/fix")
        assert response.status_code == (200 if finding["fix_available"] else 409)


def test_no_canned_fix_is_left_unused():
    fixable = {
        finding["id"]
        for piece in data.PIECES
        for finding in data.findings_for_piece(piece)
        if finding["fix_available"]
    }

    assert set(engine.FIXES) == fixable


def test_the_fix_for_the_split_claim_uses_the_approved_figure(client):
    response = client.post("/engine/findings/fnd-agency-blog-06/fix")

    assert response.json()["original"] == "by 80%"
    assert response.json()["suggested"] == "by 38%"


def test_replay_is_identical_and_keeps_the_verdict(client):
    response = client.post("/engine/verdicts/fnd-agency-blog-07/replay")

    body = response.json()
    assert body["identical"] is True
    assert body["verdict"] == "UNSURE"
    assert body["manifest"]["rule_id"] == "R-TONE-02"


def test_the_eval_gate_passes(client):
    response = client.post("/engine/eval/gate", json={"proposal": {"id": "p"}})

    assert response.json()["passed"] is True


def test_impact_lists_drafts_and_published_pieces(client):
    affected = client.get("/memory/impact?fact_id=F-002").json()

    assert {item["state"] for item in affected} == {"resolving", "published"}
    assert all(set(item) == {"content_id", "state", "claim_text"} for item in affected)


@pytest.mark.parametrize(
    ("finding_id", "count"),
    [("fnd-agency-blog-01", 0), ("fnd-agency-blog-03", 1), ("fnd-agency-blog-07", 2)],
)
def test_precedents_return_zero_to_two(client, finding_id, count):
    found = client.get(f"/memory/precedents?finding_id={finding_id}").json()

    assert len(found) == count
    for precedent in found:
        assert set(precedent) == {
            "decision_id",
            "rule_id",
            "rule_version",
            "channel",
            "reason",
            "reviewer",
            "date",
        }


def test_precedents_belong_to_the_rule_of_their_finding():
    for finding_id, precedents in memory.PRECEDENTS_BY_FINDING.items():
        _, finding = data.find_finding(finding_id)
        assert {item["rule_id"] for item in precedents} == {finding["rule_id"]}


def test_every_graph_edge_joins_two_nodes(client):
    graph = client.get("/memory/graph?root=F-002").json()

    ids = {node["id"] for node in graph["nodes"]}
    assert "F-002" in ids
    for edge in graph["edges"]:
        assert {edge["source"], edge["target"]} <= ids


def test_disclosure_lists_models_masking_and_routes(client):
    body = client.get("/gateway/reviews/rev-demo-agency-blog/disclosure").json()

    assert body["masked"] == {"PRODUCT": 1}
    assert body["models"] and body["routes"]


def test_masking_preview_hides_the_codename(client):
    body = client.get("/gateway/reviews/rev-demo-agency-blog/masking-preview").json()

    assert "Bluewren" in body["original"]
    assert "Bluewren" not in body["sent"]
    assert "[PRODUCT_1]" in body["sent"]


def test_governance_returns_two_proposals_that_passed(client):
    proposals = client.post("/governance/run").json()

    assert len(proposals) == 2
    for proposal in proposals:
        assert proposal["eval"]["passed"] is True
        assert proposal["status"] == "pending"
        assert proposal["kind"] in ("amendment", "anchor", "term", "severity")


def test_proposals_quote_the_real_rules_and_real_text():
    rules = {rule["id"]: rule for rule in data.rules()}
    chunks = data.chunks_for_piece("agency-blog")
    highlighted = {
        "R-TONE-02": "quietly start looking elsewhere",
        "R-TERM-03": "newbies",
    }

    for proposal in governance.proposals():
        assert proposal["current"] == rules[proposal["rule_id"]]["text"]
        for span in proposal["evidence"]["examples"]:
            text = chunks[span["chunk_id"]][span["start"] : span["end"]]
            assert text == highlighted[proposal["rule_id"]]


def test_spot_checks_return_one_item(client):
    assert len(client.get("/governance/spot-checks").json()) == 1


def test_llm_call_gives_ingest_the_draft_rules_and_the_conflict():
    result = gateway.llm_call("ingest", "internal", [], {})

    assert len(result["rules"]) == len(data.rules())
    assert result["conflicts"] == [{"clause_refs": ["§2.4", "§3.4"]}]


@pytest.mark.parametrize("purpose", ["visual", "classify"])
def test_llm_call_returns_a_verdict_per_rule(purpose):
    result = gateway.llm_call(purpose, "public", ["R-VIS-03"], {})

    assert [item["rule_id"] for item in result["verdicts"]] == ["R-VIS-03"]
    assert result["verdicts"][0]["verdict"] in ("VIOLATION", "UNSURE", "PASS")


def test_llm_call_fails_loudly_on_an_unknown_purpose():
    with pytest.raises(ValueError, match="purpose"):
        gateway.llm_call("something-else", "public", [], {})


def paths(router) -> set[str]:
    app = FastAPI()
    app.include_router(router)
    return set(app.openapi()["paths"])


def test_each_flag_controls_its_own_routes(monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "false")
    monkeypatch.setenv("USE_MOCK_GATEWAY", "true")
    monkeypatch.setenv("USE_MOCK_MEMORY", "false")

    mounted = paths(build_router())

    assert "/gateway/reviews/{review_id}/disclosure" in mounted
    assert "/memory/impact" not in mounted
    assert "/engine/reviews" not in mounted
    assert "/governance/run" not in mounted


def test_clients_use_the_mocks_while_the_flags_are_on(monkeypatch):
    monkeypatch.delenv("USE_MOCK_ENGINE", raising=False)
    monkeypatch.delenv("USE_MOCK_GATEWAY", raising=False)

    assert engine_client.start_review("cv-1", "banner", 1) == "rev-demo-banner"
    result = gateway_client.llm_call("ingest", "internal", [], {}, session=None)

    assert "rules" in result


def test_the_engine_client_refuses_to_pretend_when_the_mock_is_off(monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "false")

    with pytest.raises(NotImplementedError):
        engine_client.start_review("cv-1", "blog", 1)


def test_the_gateway_client_gives_the_real_gateway_its_session(monkeypatch):
    """The gateway only logs a call when it has a session, so one must reach it."""
    received = {}

    def fake_call(purpose, data_class, rule_ids, payload, **kwargs):
        received.update(kwargs)
        return {"ok": True}

    monkeypatch.setenv("USE_MOCK_GATEWAY", "false")
    fake_llm = SimpleNamespace(call=fake_call)
    monkeypatch.setitem(sys.modules, "app.gateway.llm", fake_llm)
    monkeypatch.setattr(app.gateway, "llm", fake_llm, raising=False)
    session = object()

    gateway_client.llm_call(
        "visual", "public", [], {}, session=session, review_id="review-1"
    )

    assert received == {"session": session, "review_id": "review-1"}
