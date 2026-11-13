"""Block 8: the pre-commit hook. The tests run the hook's own entry line from
.pre-commit-hooks.yaml, so a mistake in the definition fails here."""

from __future__ import annotations

import io
import shlex
import subprocess
import time
import tomllib
from pathlib import Path

import pytest
import yaml
from brandlint_cli import __version__
from brandlint_cli.cli import main
from conftest import ROOT, TOKEN
from integrations.fixtures.fake_brandlint import FakeBrandLint

HOOKS = {h["id"]: h for h in yaml.safe_load((ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))}


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def staged_repo(repo):
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    (repo / "docs" / "violating.md").write_text("# New\n\nTarnhollow Onramp again.\n", encoding="utf-8")
    (repo / "docs" / "clean.md").write_text("# Edited, but not staged\n\nTarnhollow Landing.\n", encoding="utf-8")
    git(repo, "add", "docs/violating.md")
    return repo


def run_hook(repo, hook_id, files, server, *extra, token=TOKEN):
    """What pre-commit does: the entry line, then the staged file names."""
    argv = shlex.split(HOOKS[hook_id]["entry"])
    assert argv[0] == "brandlint"
    out, err = io.StringIO(), io.StringIO()
    environment = {"BRANDLINT_SERVER": server.url}
    if token:
        environment["BRANDLINT_TOKEN"] = token
    code = main(
        [*argv[1:], "--root", str(repo), *extra, *files],
        environ=environment,
        out=out,
        err=err,
        sleep=lambda seconds: time.sleep(0.01),
    )
    return code, out.getvalue(), err.getvalue()


def test_the_hook_fails_a_commit_with_a_blocking_finding_and_prints_a_short_report(staged_repo):
    with FakeBrandLint(outcome="fail", polls_before_done=0) as server:
        code, out, _ = run_hook(staged_repo, "brandlint", ["docs/violating.md"], server)
    assert code == 1
    lines = out.strip().splitlines()
    assert lines[0].startswith("docs/violating.md:3: Retired product name")
    assert "https://app.example/ci/runs/run-1#finding-" in lines[0]
    assert lines[-1] == "brandlint: failed."
    assert len(lines) <= 3 and all(len(line) < 220 for line in lines)


def test_a_clean_commit_passes_quietly(staged_repo):
    with FakeBrandLint(outcome="pass", polls_before_done=0) as server:
        code, out, _ = run_hook(staged_repo, "brandlint", ["docs/violating.md"], server)
    assert code == 0 and out.strip() == "brandlint: passed."


def test_only_the_staged_files_are_sent(staged_repo):
    with FakeBrandLint(outcome="pass", polls_before_done=0) as server:
        # pre-commit passes the staged names; the unstaged edit must not go with them.
        run_hook(staged_repo, "brandlint", ["docs/violating.md", "docs/clean.md"], server)
    sent = [f["path"] for run in server.runs.values() for f in run["files"]]
    assert sent == ["docs/violating.md"]


def test_a_file_that_is_not_copy_is_never_sent(staged_repo):
    (staged_repo / "src" / "app.py").write_text("X = 'Tarnhollow Onramp'\n", encoding="utf-8")
    git(staged_repo, "add", "src/app.py")
    with FakeBrandLint(outcome="pass", polls_before_done=0) as server:
        run_hook(staged_repo, "brandlint", ["docs/violating.md", "src/app.py"], server)
    sent = [f["path"] for run in server.runs.values() for f in run["files"]]
    assert "src/app.py" not in sent


def test_offline_warns_in_one_line_and_lets_the_commit_through(staged_repo):
    with FakeBrandLint(outcome="down") as server:
        code, out, err = run_hook(staged_repo, "brandlint", ["docs/violating.md"], server)
    assert code == 0
    assert len(out.strip().splitlines()) == 1 and "Not blocking this commit" in out
    assert TOKEN not in out + err


def test_a_slow_server_times_out_into_the_same_warning(staged_repo):
    with FakeBrandLint(outcome="slow") as server:
        code, out, _ = run_hook(staged_repo, "brandlint", ["docs/violating.md"], server, "--timeout", "0.3")
    assert code == 0 and "Not blocking this commit" in out


def test_strict_makes_an_unreachable_server_block(staged_repo):
    with FakeBrandLint(outcome="down") as server:
        code, out, _ = run_hook(staged_repo, "brandlint", ["docs/violating.md"], server, "--strict")
    assert code == 3 and "could not check" in out


def test_a_real_failure_is_never_let_through_by_the_warn_mode(staged_repo):
    with FakeBrandLint(outcome="unsure", polls_before_done=0) as server:
        code, _, _ = run_hook(staged_repo, "brandlint", ["docs/violating.md"], server)
    assert code == 1


# --- The definition itself --------------------------------------------------------------


def test_the_hook_definitions_are_what_pre_commit_needs():
    commit, push = HOOKS["brandlint"], HOOKS["brandlint-push"]
    assert commit["language"] == push["language"] == "python"
    assert commit["pass_filenames"] is True and set(commit["types_or"]) == {"markdown", "text", "html", "json", "yaml"}
    assert commit["stages"] == ["pre-commit"] and push["stages"] == ["pre-push"]
    assert "--staged" in commit["entry"] and "--staged" not in push["entry"]
    for hook in (commit, push):
        assert "--on-error warn" in hook["entry"] and "--timeout 20" in hook["entry"]


def test_the_root_package_installs_the_same_cli_as_the_cli_folder():
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    own = tomllib.loads((ROOT / "cli" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert root["name"] == own["name"] and root["version"] == own["version"] == __version__
    assert root["dependencies"] == own["dependencies"] and root["scripts"] == own["scripts"]
    assert Path(ROOT / "cli" / "src" / "brandlint_cli" / "cli.py").is_file()
