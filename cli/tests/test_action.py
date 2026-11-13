"""Block 7: the GitHub Action's runner, against the fake BrandLint and the fake GitHub."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
import yaml
from conftest import ROOT, TOKEN
from integrations.fixtures.fake_brandlint import FakeBrandLint
from integrations.fixtures.fake_github import FakeGitHub

ACTION = ROOT / "integrations" / "github-action"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def pull(repo):
    """A pull request: a base commit, then a change to one copy file. Returns the base sha."""
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "docs" / "clean.md").write_text("# Welcome\n\nA changed line about Tarnhollow Landing.\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "edit")
    return base


def run_action(repo, tmp_path, base, *, brandlint: FakeBrandLint, github: FakeGitHub, head_repo="acme/site", **extra):
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 7,
                    "base": {"sha": base, "repo": {"full_name": "acme/site"}},
                    "head": {"repo": {"full_name": head_repo}},
                }
            }
        ),
        encoding="utf-8",
    )
    summary, outputs = tmp_path / "summary.md", tmp_path / "output.txt"
    for path in (summary, outputs):
        path.write_text("", encoding="utf-8")
    environment = {
        **os.environ,
        "BRANDLINT_TOKEN": TOKEN,
        "INPUT_SERVER": brandlint.url,
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_OUTPUT": str(outputs),
        "GITHUB_TOKEN": "ghs_FAKEGITHUBTOKEN",
        "GITHUB_API_URL": github.url,
        "GITHUB_REPOSITORY": "acme/site",
        "GITHUB_SHA": "feedface",
        "PYTHONPATH": str(ROOT / "cli" / "src"),
    }
    environment.update(extra)
    done = subprocess.run(
        [sys.executable, str(ACTION / "run.py")], cwd=repo, env=environment, capture_output=True, text=True, check=False
    )
    return done, summary.read_text(encoding="utf-8"), outputs.read_text(encoding="utf-8")


def test_a_pull_request_that_passes_says_so_in_the_summary_and_one_comment(repo, tmp_path, pull):
    with FakeBrandLint(outcome="pass", polls_before_done=0) as brandlint, FakeGitHub() as github:
        done, summary, outputs = run_action(repo, tmp_path, pull, brandlint=brandlint, github=github)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "result=pass" in outputs and "### BrandLint: Passed" in summary
    [comment] = github.comments[7]
    assert "No finding blocks this run" in comment["body"] and "not an approval" in comment["body"]
    sent = [f["path"] for run in brandlint.runs.values() for f in run["files"]]
    assert sent == ["docs/clean.md"]  # only what the pull request changed


def test_a_failing_pull_request_gets_annotations_a_table_with_links_and_a_failing_exit(repo, tmp_path, pull):
    with FakeBrandLint(outcome="fail", polls_before_done=0) as brandlint, FakeGitHub() as github:
        done, summary, outputs = run_action(repo, tmp_path, pull, brandlint=brandlint, github=github)
    assert done.returncode == 1
    assert "::error file=docs/clean.md,line=3" in done.stdout
    assert "result=fail" in outputs and "run-url=https://app.example/ci/runs/run-1" in outputs
    body = github.comments[7][0]["body"]
    assert "| Where | Severity | Finding | Rule | Effect |" in body
    assert "[open](https://app.example/ci/runs/run-1#finding-" in body
    assert "Tarnhollow Onramp" not in body  # titles and rule ids, never the quoted draft


def test_a_new_push_updates_the_same_comment_instead_of_adding_another(repo, tmp_path, pull):
    with FakeBrandLint(outcome="fail", polls_before_done=0) as brandlint, FakeGitHub() as github:
        run_action(repo, tmp_path, pull, brandlint=brandlint, github=github)
        (repo / "docs" / "clean.md").write_text("# Welcome\n\nAnother edit.\n", encoding="utf-8")
        git(repo, "commit", "-q", "-am", "another")
        brandlint.outcome = "pass"
        run_action(repo, tmp_path, pull, brandlint=brandlint, github=github)
    assert len(github.comments[7]) == 1
    assert "Passed" in github.comments[7][0]["body"]


def test_a_fork_pull_request_does_not_run_and_is_never_a_pass(repo, tmp_path, pull):
    with FakeBrandLint(outcome="pass", polls_before_done=0) as brandlint, FakeGitHub() as github:
        done, summary, outputs = run_action(
            repo, tmp_path, pull, brandlint=brandlint, github=github, head_repo="someone/site"
        )
        assert brandlint.requests == []  # BrandLint was not called
        assert done.returncode == 1 and "fork" in done.stdout and "result=skipped" in outputs
        skipped, _, outputs = run_action(
            repo, tmp_path, pull, brandlint=brandlint, github=github, head_repo="someone/site", INPUT_ON_FORK="skip"
        )[0], None, None
    assert skipped.returncode == 0  # a maintainer chose to leave fork pull requests unchecked


def test_an_empty_token_is_a_failure_to_run_not_a_pass(repo, tmp_path, pull):
    with FakeBrandLint(outcome="pass") as brandlint, FakeGitHub() as github:
        done, _, outputs = run_action(repo, tmp_path, pull, brandlint=brandlint, github=github, BRANDLINT_TOKEN="")
    assert done.returncode == 1 and "result=skipped" in outputs


def test_the_token_never_appears_in_the_log_the_summary_or_the_comment(repo, tmp_path, pull):
    with FakeBrandLint(outcome="down") as brandlint, FakeGitHub() as github:
        done, summary, outputs = run_action(repo, tmp_path, pull, brandlint=brandlint, github=github)
    # The one line that must carry it is the instruction that makes GitHub hide it.
    kept = [line for line in done.stdout.splitlines() if not line.startswith("::add-mask::")]
    log = "\n".join(kept)
    everything = log + done.stderr + summary + outputs + json.dumps(github.comments)
    assert TOKEN not in everything and "ghs_FAKEGITHUBTOKEN" not in everything
    assert f"::add-mask::{TOKEN}" in done.stdout  # GitHub is told to hide it in every later line
    assert done.returncode == 3  # BrandLint errored and on-error is fail


def test_on_error_pass_lets_an_unreachable_server_through_with_a_warning(repo, tmp_path, pull):
    with FakeBrandLint(outcome="down") as brandlint, FakeGitHub() as github:
        done, summary, _ = run_action(repo, tmp_path, pull, brandlint=brandlint, github=github, INPUT_ON_ERROR="pass")
    assert done.returncode == 0 and "could not check" in done.stdout.lower()


def test_fail_on_none_reports_a_failure_without_failing_the_check(repo, tmp_path, pull):
    with FakeBrandLint(outcome="fail", polls_before_done=0) as brandlint, FakeGitHub() as github:
        done, _, outputs = run_action(repo, tmp_path, pull, brandlint=brandlint, github=github, INPUT_FAIL_ON="none")
    assert done.returncode == 0 and "result=fail" in outputs


def test_a_comment_that_can_not_be_posted_does_not_change_the_result(repo, tmp_path, pull):
    with FakeBrandLint(outcome="fail", polls_before_done=0) as brandlint, FakeGitHub() as github:
        done, _, _ = run_action(repo, tmp_path, pull, brandlint=brandlint, github=github, GITHUB_API_URL="http://127.0.0.1:9")
    assert done.returncode == 1 and "Could not post the pull request comment" in done.stdout


# --- The files that ship ----------------------------------------------------------------


def test_the_example_workflow_asks_for_the_least_it_can_and_pins_and_cancels():
    workflow = yaml.safe_load((ACTION / "example-workflow.yml").read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "write"}
    assert workflow["concurrency"]["cancel-in-progress"] is True
    steps = workflow["jobs"]["BrandLint"]["steps"]
    assert steps[0]["with"]["fetch-depth"] == 0  # the base commit has to be there
    assert "COMMIT_SHA" in steps[1]["uses"]  # pinned by commit, not a tag
    assert "pull_request_target" not in json.dumps(workflow)


def test_the_actions_own_steps_are_pinned_and_its_dependencies_are_hashed():
    action = yaml.safe_load((ACTION / "action.yml").read_text(encoding="utf-8"))
    uses = [s["uses"] for s in action["runs"]["steps"] if "uses" in s]
    assert all("@" in u and len(u.split("@")[1].split()[0]) == 40 for u in uses)  # a full commit SHA
    requirements = (ACTION / "requirements.txt").read_text(encoding="utf-8")
    pins = [line for line in requirements.splitlines() if "==" in line]
    assert pins and requirements.count("--hash=sha256:") >= len(pins)
    install = next(s["run"] for s in action["runs"]["steps"] if "pip install" in s.get("run", ""))
    assert "--require-hashes" in install
