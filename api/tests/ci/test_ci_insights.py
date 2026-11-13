"""Block 9: CI activity in the insights view."""

from __future__ import annotations

# ruff: noqa: F811
from tests.ci.test_runs import bot, mock_app, person, request, text_file  # noqa: F401


def test_the_summary_counts_runs_results_and_token_use_for_the_workspace_only(bot, world, mock_app):
    bot.post("/ci/runs", json=request(text_file("a.md", "One."), sha="1"))
    done = bot.post("/ci/runs", json=request(text_file("b.md", "Two."), sha="2")).json()
    bot.get(f"/ci/runs/{done['id']}")  # a read settles the result
    manager = person(mock_app, world.a.admin)
    summary = manager.get("/insights/ci").json()
    # Two from the job, and the one the two-org world already holds.
    assert summary["runs_30d"] == 3 and summary["runs_7d"] == 3
    assert sum(summary["by_result"].values()) == 3
    assert summary["tokens"][0]["name"] == "CI" and summary["tokens"][0]["runs_7d"] == 2
    other = person(mock_app, world.b.admin).get("/insights/ci").json()
    # Its own run and token from the world, and nothing of A's.
    assert other["runs_30d"] == 1 and [t["name"] for t in other["tokens"]] == [other["tokens"][0]["name"]]
    assert all(t["name"] != "CI" for t in other["tokens"])


def test_only_managers_and_admins_see_it_and_it_is_off_until_enabled(world, mock_app, monkeypatch):
    assert person(mock_app, world.a.creator).get("/insights/ci").status_code == 403
    assert person(mock_app, world.a.reviewer).get("/insights/ci").status_code == 403
    monkeypatch.delenv("CI_INTEGRATION_ENABLED")
    assert person(mock_app, world.a.admin).get("/insights/ci").status_code == 404
