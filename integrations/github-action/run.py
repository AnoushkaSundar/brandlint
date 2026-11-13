"""Runs `brandlint check` for a pull request and reports to GitHub.

Standard library plus the pinned brandlint-cli. It never runs anything from the repo being
checked: it only reads its files. Exit codes follow the check: 0 passed (or not run, by choice),
1 a finding blocks (or a fork pull request, which has no secrets), 3 BrandLint errored and
`on-error` is `fail`.

Blocking the merge is done by GitHub's branch protection (require this check), not by this
script.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "cli" / "src"))  # when not installed

import report  # noqa: E402
from brandlint_cli import output  # noqa: E402


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def write_output(name: str, value: str) -> None:
    path = env("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def write_summary(text: str) -> None:
    path = env("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def event() -> dict:
    path = env("GITHUB_EVENT_PATH")
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        return {}


def is_fork(payload: dict) -> bool:
    pull = payload.get("pull_request") or {}
    head = ((pull.get("head") or {}).get("repo") or {}).get("full_name")
    base = ((pull.get("base") or {}).get("repo") or {}).get("full_name")
    return bool(head and base and head != base)


def stop_without_running(message: str, *, skip: bool) -> int:
    print(f"::{'notice' if skip else 'error'} title=BrandLint::{message}")
    write_summary(f"### BrandLint: Not run\n\n{message}\n")
    write_output("result", "skipped")
    write_output("run-url", "")
    # Never a pass: a check that did not run must not look like one that did, unless a
    # maintainer chose to skip it (which GitHub then shows as a green job, on purpose).
    return 0 if skip else 1


def main() -> int:
    token = env("BRANDLINT_TOKEN")
    if token:
        print(f"::add-mask::{token}")
    payload = event()
    pull = payload.get("pull_request") or {}
    skip_forks = env("INPUT_ON_FORK", "fail") == "skip"

    if is_fork(payload) or not token:
        reason = (
            "This pull request comes from a fork, so GitHub does not give it the BrandLint token."
            if is_fork(payload)
            else "BRANDLINT_TOKEN is empty, so BrandLint cannot be reached."
        )
        return stop_without_running(
            f"{reason} The check did not run. A maintainer can run it from a branch in this repo, "
            "or set on-fork: skip to leave fork pull requests unchecked.",
            skip=skip_forks and is_fork(payload),
        )

    base_sha = (pull.get("base") or {}).get("sha") or env("GITHUB_BASE_SHA")
    command = [
        sys.executable, "-m", "brandlint_cli", "check",
        "--format", "json",
        "--server", env("INPUT_SERVER"),
        "--on-error", env("INPUT_ON_ERROR", "fail"),
        "--config", env("INPUT_CONFIG", ".brandlint.yml"),
    ]
    if base_sha:
        command += ["--changed-against", base_sha, "--base-sha", base_sha]
    done = subprocess.run(command, capture_output=True, text=True, env={**os.environ}, check=False)
    sys.stderr.write(done.stderr)

    try:
        data = json.loads(done.stdout)
    except ValueError:
        print("::error title=BrandLint::The BrandLint command line tool gave no result.")
        write_output("result", "error")
        return 3 if env("INPUT_ON_ERROR", "fail") == "fail" else 0

    statuses, warnings, skipped = data["runs"], data["warnings"], [(s["path"], s["reason"]) for s in data["skipped"]]
    result = data["result"]
    print(output.github(statuses, warnings, skipped, result), end="")
    body = report.markdown(result, statuses, warnings, skipped)
    write_summary(body)
    write_output("result", result)
    write_output("run-url", statuses[0]["url"] if statuses else "")

    pr = pull.get("number")
    if pr and env("GITHUB_TOKEN") and env("GITHUB_REPOSITORY"):
        posted = report.try_upsert(
            env("GITHUB_API_URL", "https://api.github.com"), env("GITHUB_TOKEN"), env("GITHUB_REPOSITORY"), pr, body
        )
        if posted is None:
            print("::warning title=BrandLint::Could not post the pull request comment. The check result stands.")

    if result == "fail" and env("INPUT_FAIL_ON", "violations") == "none":
        return 0
    return int(data["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
