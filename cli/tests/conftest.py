"""Fixtures for the CLI tests. They use the fake repo and the fake BrandLint server in
integrations/fixtures, which are standard-library only."""

from __future__ import annotations

import io
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cli" / "src"))

from brandlint_cli.cli import main

from integrations.fixtures.fake_brandlint import FakeBrandLint

TOKEN = "bl_SUPERSECRETTOKENVALUE123"


@pytest.fixture()
def repo(tmp_path):
    """A fresh copy of the fake repo, so a test can add files or links to it."""
    target = tmp_path / "repo"
    shutil.copytree(ROOT / "integrations" / "fixtures" / "repo", target)
    return target


@pytest.fixture()
def check(repo):
    """Runs `brandlint check` in the repo against a server, and returns (exit code, out, err)."""

    def run(*argv, server: FakeBrandLint | None = None, env: dict | None = None, token: str = TOKEN):
        out, err = io.StringIO(), io.StringIO()
        environment = {"BRANDLINT_TOKEN": token} if token else {}
        if server is not None:
            environment["BRANDLINT_SERVER"] = server.url
        environment.update(env or {})
        code = main(
            ["check", "--root", str(repo), *argv],
            environ=environment,
            out=out,
            err=err,
            sleep=lambda seconds: time.sleep(0.01),
        )
        return code, out.getvalue(), err.getvalue()

    return run
