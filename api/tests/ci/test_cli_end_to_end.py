"""Block 5's gate: the CLI passes and fails the fixture repo correctly, end to end, against the
real API on the mock engine. The CLI is the real one, talking over a real socket."""

from __future__ import annotations

import io
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from integrations.fixtures import ALLOWED_PORTS

from tests.ci.test_policy_and_waiver import waive_everything
from tests.ci.test_runs import mock_app, person  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "cli" / "src"))

from brandlint_cli.cli import main as cli_main  # noqa: E402


@pytest.fixture()
def live_server(mock_app):  # noqa: F811
    server = uvicorn.Server(uvicorn.Config(mock_app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    ALLOWED_PORTS.add(port)
    yield f"http://127.0.0.1:{port}"
    ALLOWED_PORTS.discard(port)
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def fixture_repo(tmp_path):
    target = tmp_path / "repo"
    shutil.copytree(ROOT / "integrations" / "fixtures" / "repo", target)
    config = target / ".brandlint.yml"
    kept = [line for line in config.read_text(encoding="utf-8").splitlines() if not line.startswith("server:")]
    config.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return target


def run_cli(repo, server, token, *extra):
    out, err = io.StringIO(), io.StringIO()
    code = cli_main(
        ["check", "--root", str(repo), "--server", server, "--timeout", "60", *extra],
        environ={"BRANDLINT_TOKEN": token, "GITHUB_REPOSITORY": "acme/site", "GITHUB_SHA": "abc123"},
        out=out,
        err=err,
        sleep=lambda seconds: time.sleep(0.05),
    )
    return code, out.getvalue(), err.getvalue()


def test_the_cli_fails_the_fixture_repo_a_reviewer_waives_it_and_the_cli_then_passes(
    world, client_for, live_server, fixture_repo, mock_app  # noqa: F811
):
    token = client_for(world.a.admin).post("/ci/tokens", json={"name": "CI"}).json()["token"]

    code, out, err = run_cli(fixture_repo, live_server, token)
    assert code == 1, out + err
    assert "BrandLint FAILED." in out and "BLOCKS" in out and "/ci/runs/" in out
    assert token not in out + err

    # The same command again finds the same runs: nothing new is made.
    code_again, _, _ = run_cli(fixture_repo, live_server, token, "--format", "json")
    assert code_again == 1

    reviewer = person(mock_app, world.a.reviewer)
    import json

    data = json.loads(run_cli(fixture_repo, live_server, token, "--format", "json")[1])
    for run in data["runs"]:
        waive_everything(reviewer, run)

    code, out, err = run_cli(fixture_repo, live_server, token)
    assert code == 0, out + err
    assert "BrandLint PASSED." in out


def test_the_cli_reports_a_refused_token_as_an_error_not_a_pass(world, live_server, fixture_repo):
    code, out, err = run_cli(fixture_repo, live_server, "bl_not-a-real-token-at-all")
    assert code == 3 and "401" in out and "bl_not-a-real-token-at-all" not in out + err
