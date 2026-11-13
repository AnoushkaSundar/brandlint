"""Block 9: this repo checks its own copy, and the workflow that does it is inert until set up."""

from __future__ import annotations

import json

import yaml
from brandlint_cli.config import load
from conftest import ROOT


def test_the_repos_own_config_matches_the_demo_copy_and_nothing_else():
    config = load(ROOT / ".brandlint.yml")
    assert config.rule_for("demo/pieces/linkedin-post.html").extract == "plain"
    assert config.rule_for("demo/pieces/agency-blog.docx") is not None
    assert config.rule_for("api/app/main.py") is None  # code is never copy
    assert config.rule_for("demo/pieces/banner.chunks.json") is None


def test_the_dogfood_workflow_does_nothing_until_configured_and_asks_for_the_least():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "brandlint.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["BrandLint"]
    assert "vars.BRANDLINT_SERVER != ''" in job["if"]
    assert "head.repo.full_name == github.repository" in job["if"]  # no forks: they have no secrets
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "write"}
    assert "pull_request_target" not in json.dumps(workflow)
    assert any(step.get("uses") == "./integrations/github-action" for step in job["steps"])


def test_the_ci_flag_is_off_by_default_everywhere_it_is_set():
    compose = (ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert compose.count("CI_INTEGRATION_ENABLED:-false") == 2  # the API and the web build
    assert "CI_INTEGRATION_ENABLED=false" in (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_CI_ENABLED=false" in (ROOT / "web" / "Dockerfile.prod").read_text(encoding="utf-8").replace("ARG ", "")
