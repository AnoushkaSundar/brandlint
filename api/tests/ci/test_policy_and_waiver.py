"""Block 3: the workspace's policy, the verdict on a real run, and waiving through the web app."""

from __future__ import annotations

from app import db
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.ci.test_runs import bot, mock_app, person, request, text_file  # noqa: F401


def waive_everything(reviewer: TestClient, run: dict) -> int:
    """A reviewer settles every blocking finding in the web app: override, or resolve an UNSURE."""
    done = 0
    for file in run["files"]:
        for found in file["findings"]:
            if not found["blocking"]:
                continue
            action = "resolve" if found["verdict"] == "UNSURE" else "override"
            response = reviewer.post(
                f"/workflow/content/{file['content_id']}/findings/{found['id']}/decisions",
                json={"action": action, "reason": "Approved by brand review."},
            )
            assert response.status_code == 201, response.text
            done += 1
    return done


def test_a_run_with_blocking_findings_fails_and_a_waiver_in_the_web_app_flips_a_rerun_to_pass(
    bot, world, mock_app  # noqa: F811
):
    body = request(text_file("docs/a.md", "Some copy."))
    created = bot.post("/ci/runs", json=body).json()
    run = bot.get(f"/ci/runs/{created['id']}").json()
    assert run["state"] == "done" and run["result"] == "fail"
    assert run["reasons"][0].endswith("block this run.") or "blocks this run" in run["reasons"][0]
    assert any(f["blocking"] for file in run["files"] for f in file["findings"])

    reviewer = person(mock_app, world.a.reviewer)
    assert waive_everything(reviewer, run) > 0

    # Re-running the same copy finds the same review, and reads what the reviewer decided.
    again = bot.post("/ci/runs", json=body)
    assert again.json()["id"] == created["id"]
    run = bot.get(f"/ci/runs/{created['id']}").json()
    assert (run["result"], run["reasons"]) == ("pass", [])
    assert not any(f["blocking"] for file in run["files"] for f in file["findings"])


def test_the_policy_is_a_workspace_setting_an_admin_changes(world, client_for, bot):  # noqa: F811
    admin = client_for(world.a.admin)
    assert admin.get("/ci/policy").json() == {
        "severity_threshold": "medium",
        "fail_on_unsure": True,
        "ignore_rules": [],
        "max_waiting_minutes": 15,
    }
    changed = {"severity_threshold": "critical", "fail_on_unsure": False, "ignore_rules": [], "max_waiting_minutes": 30}
    assert admin.put("/ci/policy", json=changed).json() == changed
    assert bot.get("/ci/policy").json()["severity_threshold"] == "critical"  # a job can read it
    assert client_for(world.b.admin).get("/ci/policy").json()["severity_threshold"] == "medium"
    assert client_for(world.a.creator).put("/ci/policy", json=changed).status_code == 403
    assert bot.put("/ci/policy", json=changed).status_code == 401  # a token can't change it


def test_a_looser_policy_lets_the_same_run_through(world, client_for, bot):  # noqa: F811
    created = bot.post("/ci/runs", json=request(text_file("docs/a.md", "Some copy."))).json()
    assert bot.get(f"/ci/runs/{created['id']}").json()["result"] == "fail"
    client_for(world.a.admin).put(
        "/ci/policy",
        json={"severity_threshold": "critical", "fail_on_unsure": False, "ignore_rules": [], "max_waiting_minutes": 15},
    )
    run = bot.get(f"/ci/runs/{created['id']}").json()
    # Only critical violations can still block, so the result follows the new policy.
    still = [f for file in run["files"] for f in file["findings"] if f["blocking"]]
    assert all(f["severity"] == "critical" and f["verdict"] == "VIOLATION" for f in still)
    assert run["result"] == ("fail" if still else "pass")


def test_ignore_rules_must_be_rules_that_exist_and_are_approved(world, client_for):
    admin = client_for(world.a.admin)
    base = {"severity_threshold": "medium", "fail_on_unsure": True, "max_waiting_minutes": 15}
    assert admin.put("/ci/policy", json={**base, "ignore_rules": ["R-NOPE"]}).status_code == 422
    from app.admin.models import Rule

    with db.get_sessionmaker()() as session:
        approved = session.scalar(
            select(Rule.id).where(Rule.org_id == world.a.org.id, Rule.status == "approved")
        )
        draft = session.scalar(
            select(Rule.id).where(Rule.org_id == world.a.org.id, Rule.status == "draft")
        )
    assert draft is not None and admin.put("/ci/policy", json={**base, "ignore_rules": [draft]}).status_code == 422
    assert admin.put("/ci/policy", json={**base, "ignore_rules": [approved]}).status_code == 200


def test_an_empty_rulebook_is_an_error_with_a_helpful_reason_never_a_pass(world, client_for, mock_app):  # noqa: F811
    from app.admin.models import Rule
    from sqlalchemy import update

    with db.get_sessionmaker()() as session:
        session.execute(update(Rule).where(Rule.org_id == world.a.org.id).values(status="retired"))
        session.commit()
    token = client_for(world.a.admin).post("/ci/tokens", json={"name": "CI"}).json()["token"]
    bot_a = TestClient(mock_app, raise_server_exceptions=False)
    bot_a.headers["Authorization"] = f"Bearer {token}"
    created = bot_a.post("/ci/runs", json=request(text_file("docs/a.md", "Some copy.")))
    run = bot_a.get(f"/ci/runs/{created.json()['id']}").json()
    assert run["state"] == "error" and run["result"] is None
    assert "no approved rules" in run["reasons"][0]


def test_a_review_that_does_not_finish_in_time_is_an_error_not_a_pass(world, client_for, bot, monkeypatch):  # noqa: F811
    from app.clients import engine as engine_client

    monkeypatch.setattr(engine_client, "review_status", lambda review_id, session: "running")
    created = bot.post("/ci/runs", json=request(text_file("docs/a.md", "Some copy."))).json()
    assert bot.get(f"/ci/runs/{created['id']}").json()["state"] == "running"
    client_for(world.a.admin).put(
        "/ci/policy",
        json={"severity_threshold": "medium", "fail_on_unsure": True, "ignore_rules": [], "max_waiting_minutes": 1},
    )
    from datetime import timedelta

    from app.auth.defaults import utc_now
    from app.ci.models import CIRun
    from sqlalchemy import update

    with db.get_sessionmaker()() as session:
        session.execute(update(CIRun).where(CIRun.id == created["id"]).values(created_at=utc_now() - timedelta(minutes=5)))
        session.commit()
    run = bot.get(f"/ci/runs/{created['id']}").json()
    assert run["state"] == "error" and run["result"] is None and "too long" in run["reasons"][0]


def test_a_failed_review_is_an_error(world, bot, monkeypatch):  # noqa: F811
    from app.clients import engine as engine_client

    monkeypatch.setattr(engine_client, "review_status", lambda review_id, session: "failed")
    created = bot.post("/ci/runs", json=request(text_file("docs/a.md", "Some copy."))).json()
    run = bot.get(f"/ci/runs/{created['id']}").json()
    assert run["state"] == "error" and run["result"] is None
