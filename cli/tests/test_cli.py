"""Block 5: one command that works the same locally and in CI."""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from conftest import TOKEN
from integrations.fixtures.fake_brandlint import FakeBrandLint

# --- What gets sent --------------------------------------------------------------------


def test_only_files_a_rule_matches_are_sent_and_ignored_ones_are_not(check):
    with FakeBrandLint(outcome="pass", polls_before_done=0) as server:
        code, out, _ = check(server=server)
    assert code == 0
    sent = {f["path"] for run in server.runs.values() for f in run["files"]}
    assert {"docs/clean.md", "docs/violating.md", "site/hidden.html", "i18n/en.json"} <= sent
    assert "docs/drafts/skip-me.md" not in sent  # ignored by the config
    assert "src/app.py" not in sent  # no rule says it holds copy
    assert "BrandLint PASSED." in out


def test_a_symlink_out_of_the_repo_and_an_oversized_file_are_reported_not_silently_passed(check, repo, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text("Tarnhollow Onramp.", encoding="utf-8")
    try:
        os.symlink(outside, repo / "docs" / "link.md")
    except (OSError, NotImplementedError):
        pytest.skip("this system can not make symlinks")
    (repo / "docs" / "huge.md").write_text("x" * (6 * 1024 * 1024), encoding="utf-8")
    with FakeBrandLint(outcome="pass", polls_before_done=0) as server:
        code, out, _ = check(server=server)
    sent = {f["path"] for run in server.runs.values() for f in run["files"]}
    assert "docs/link.md" not in sent and "docs/huge.md" not in sent
    assert "SKIPPED docs/link.md: a symlink that points outside the repo" in out
    assert "SKIPPED docs/huge.md" in out and "was not checked" in out


def test_a_path_outside_the_repo_is_refused(check, tmp_path):
    code, _, err = check(str(tmp_path / "elsewhere.md"), token=TOKEN)
    assert code == 2 and "outside the repo" in err


def test_a_big_repo_is_sent_in_batches(check, repo):
    for n in range(60):
        (repo / "docs" / f"page{n}.md").write_text(f"Page {n} of Tarnhollow Landing.", encoding="utf-8")
    with FakeBrandLint(outcome="pass", polls_before_done=0) as server:
        code, _, _ = check(server=server)
    assert code == 0 and server.runs_created >= 3


# --- Every outcome has its exit code ----------------------------------------------------


@pytest.mark.parametrize(
    "outcome, expected, word",
    [("pass", 0, "PASSED"), ("fail", 1, "FAILED"), ("unsure", 1, "FAILED"), ("error", 3, "COULD NOT CHECK"), ("down", 3, "COULD NOT CHECK")],
)
def test_each_outcome_gives_its_exit_code(check, outcome, expected, word):
    with FakeBrandLint(outcome=outcome, polls_before_done=1) as server:
        code, out, _ = check(server=server)
    assert code == expected and word in out


def test_a_run_that_never_finishes_times_out_as_an_error(check):
    with FakeBrandLint(outcome="slow") as server:
        code, out, _ = check("--timeout", "0.3", server=server)
    assert code == 3 and "did not finish in time" in out


def test_on_error_pass_and_warn_let_the_run_through_but_say_so_and_fail_does_not(check):
    with FakeBrandLint(outcome="down") as server:
        assert check(server=server)[0] == 3
        for mode in ("pass", "warn"):
            code, out, _ = check("--on-error", mode, server=server)
            assert code == 0 and "could not check" in out
    # A real failure is never let through by --on-error.
    with FakeBrandLint(outcome="fail", polls_before_done=0) as server:
        assert check("--on-error", "pass", server=server)[0] == 1


def test_the_findings_are_printed_with_a_link_and_only_a_short_span(check):
    with FakeBrandLint(outcome="fail", polls_before_done=0) as server:
        _, out, _ = check(server=server)
    assert "BLOCKS" in out and "https://app.example/ci/runs/run-1#finding-" in out
    assert "Run: https://app.example/ci/runs/run-1" in out


def test_json_output_has_the_result_the_runs_and_the_skipped_files(check):
    with FakeBrandLint(outcome="fail", polls_before_done=0) as server:
        code, out, _ = check("--format", "json", server=server)
    data = json.loads(out)
    assert (data["result"], data["exit_code"]) == ("fail", code == 1 and 1)
    assert data["runs"][0]["state"] == "done" and data["runs"][0]["files"]
    assert data["skipped"] == [] and data["warnings"] == []


# --- The token ---------------------------------------------------------------------------


def test_the_token_is_never_printed_even_when_the_request_fails(check):
    with FakeBrandLint(outcome="down") as server:
        code, out, err = check(server=server)
    assert code == 3
    assert TOKEN not in out + err
    # And when the server's error message happens to contain it.
    with FakeBrandLint(outcome="pass", polls_before_done=0) as server:
        code, out, err = check("--format", "json", server=server)
    assert TOKEN not in out + err


def test_the_token_can_not_be_given_as_a_flag(check):
    code, out, err = check("--token", TOKEN)
    assert code == 2


def test_a_missing_token_or_server_is_a_usage_error(check, repo):
    with FakeBrandLint(outcome="pass") as server:
        code, _, err = check(server=server, token="")
        assert code == 2 and "BRANDLINT_TOKEN" in err
    config = repo / ".brandlint.yml"
    kept = [
        line
        for line in config.read_text(encoding="utf-8").splitlines()
        if not line.startswith("server:")
    ]
    config.write_text("\n".join(kept) + "\n", encoding="utf-8")
    code, _, err = check()
    assert code == 2 and "no server" in err


def test_the_server_refusing_the_token_is_an_error_that_does_not_echo_it(check):
    class Refuses(FakeBrandLint):
        def route(self, method, path, body, auth):
            return 401, {"detail": f"bad token {TOKEN}"}

    with Refuses() as server:
        code, out, err = check(server=server)
    assert code == 3 and "401" in out and TOKEN not in out + err


# --- Config errors are clear, and exit 2 ------------------------------------------------


@pytest.mark.parametrize(
    "text, message",
    [
        ("channels: [", "isn't valid YAML"),
        ("server: x\n", "needs a 'channels' list"),
        ("channels:\n  - glob: '*.md'\n    channel: tweet\n", "channel must be one of"),
        ("channels:\n  - glob: '../*.md'\n    channel: blog\n", "can't contain '..'"),
        ("channels:\n  - glob: '*.md'\n    channel: blog\nbogus: 1\n", "unknown keys"),
    ],
)
def test_a_bad_config_exits_2_and_says_what_to_change(check, repo, text, message):
    (repo / ".brandlint.yml").write_text(text, encoding="utf-8")
    code, _, err = check()
    assert code == 2 and message in err


def test_a_missing_config_exits_2(check, repo):
    (repo / ".brandlint.yml").unlink()
    code, _, err = check()
    assert code == 2 and "No .brandlint.yml" in err


# --- Only what changed ------------------------------------------------------------------


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def init_repo(repo):
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")


def test_changed_against_sends_only_files_changed_since_the_ref(check, repo):
    init_repo(repo)
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "docs" / "clean.md").write_text("# Welcome\n\nA new line about Tarnhollow Landing.\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text("# changed, but not copy\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "edit")
    with FakeBrandLint(outcome="pass", polls_before_done=0) as server:
        code, _, _ = check("--changed-against", "main", server=server)
    sent = [f["path"] for run in server.runs.values() for f in run["files"]]
    assert code == 0 and sent == ["docs/clean.md"]


def test_a_ref_that_is_not_there_says_how_to_fetch_it(check, repo):
    init_repo(repo)
    code, _, err = check("--changed-against", "origin/main")
    assert code == 2 and "fetch" in err


def test_staged_sends_only_staged_files(check, repo):
    init_repo(repo)
    (repo / "docs" / "violating.md").write_text("# Meet the new thing\n\nHello there.\n", encoding="utf-8")
    (repo / "docs" / "clean.md").write_text("# Edited but not staged\n\nTarnhollow Landing.\n", encoding="utf-8")
    git(repo, "add", "docs/violating.md")
    with FakeBrandLint(outcome="pass", polls_before_done=0) as server:
        code, _, _ = check("--staged", server=server)
    sent = [f["path"] for run in server.runs.values() for f in run["files"]]
    assert code == 0 and sent == ["docs/violating.md"]


def test_staged_and_changed_against_together_is_a_usage_error(check):
    code, _, err = check("--staged", "--changed-against", "main")
    assert code == 2 and "not both" in err
