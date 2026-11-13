"""Which files a change touched, from git. No shell: arguments go in as a list."""

from __future__ import annotations

import subprocess
from pathlib import Path

from brandlint_cli.discover import UsageError


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        raise UsageError("git is not installed, so changed files can not be listed.") from None


def _names(output: str) -> set[str]:
    return {line.strip() for line in output.splitlines() if line.strip()}


def changed_against(root: Path, ref: str) -> set[str]:
    """Files added, copied, modified or renamed since `ref` (the merge base with HEAD)."""
    done = None
    for spec in (f"{ref}...HEAD", f"{ref}..HEAD"):
        done = _git(root, "diff", "--name-only", "--diff-filter=ACMR", spec)
        if done.returncode == 0:
            return _names(done.stdout)
    detail = ((done.stderr if done else "") or "").strip().splitlines()[-1:] or ["unknown ref"]
    raise UsageError(
        f"Could not compare with {ref!r} ({detail[0]}). In CI, check out with fetch-depth: 0, "
        f"or run: git fetch --no-tags origin {ref}"
    )


def staged(root: Path) -> set[str]:
    done = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    if done.returncode != 0:
        raise UsageError("Could not list the staged files. Is this a git repository?")
    return _names(done.stdout)
