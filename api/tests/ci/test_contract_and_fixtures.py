"""Block 0: the CI contract holds, and the fixtures (fake repo, fake GitHub, fake server) load."""

from __future__ import annotations

import base64
import json
import sys
import urllib.request
from pathlib import Path

import pytest
from app.contracts import (
    CIFile,
    CIFileResult,
    CIFinding,
    CIPolicy,
    CIRunRequest,
    CIRunStatus,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from integrations.fixtures import build
from integrations.fixtures.fake_brandlint import FakeBrandLint
from integrations.fixtures.fake_github import FakeGitHub

REPO = ROOT / "integrations" / "fixtures" / "repo"


# --- The contract ------------------------------------------------------------------------


def test_a_file_carries_text_or_a_binary_but_not_both_and_not_neither():
    assert CIFile(path="a.md", channel="blog", text="Hi").data_class.value == "public"
    CIFile(path="a.docx", channel="document", file_b64=base64.b64encode(b"x").decode())
    with pytest.raises(ValidationError):
        CIFile(path="a.md", channel="blog")
    with pytest.raises(ValidationError):
        CIFile(path="a.md", channel="blog", text="Hi", file_b64="eA==")


def test_a_run_needs_a_known_channel_and_at_least_one_file():
    with pytest.raises(ValidationError):
        CIRunRequest(repo="o/r", sha="abc", files=[])
    with pytest.raises(ValidationError):
        CIRunRequest(
            repo="o/r", sha="abc", files=[{"path": "a.md", "channel": "tweet", "text": "x"}]
        )
    request = CIRunRequest(
        repo="o/r", pr=7, sha="abc", files=[{"path": "a.md", "channel": "blog", "text": "x"}]
    )
    assert request.base_sha is None and request.pr == 7


def test_a_status_round_trips_through_json():
    status = CIRunStatus(
        id="run-1",
        state="done",
        result="fail",
        reasons=["1 blocking finding"],
        url="https://app.example/ci/runs/run-1",
        policy=CIPolicy(),
        files=[
            CIFileResult(
                path="a.md",
                content_id="c1",
                review_id="r1",
                state="done",
                findings=[
                    CIFinding(
                        id="f1",
                        rule_id="R-TERM-02",
                        severity="high",
                        verdict="VIOLATION",
                        status="open",
                        span="retired name",
                        line=3,
                        title="Retired product name",
                        url="https://app.example/ci/runs/run-1#finding-f1",
                        blocking=True,
                    )
                ],
            )
        ],
    )
    again = CIRunStatus.model_validate(json.loads(status.model_dump_json()))
    assert again == status
    assert CIPolicy().severity_threshold.value == "medium" and CIPolicy().fail_on_unsure


# --- The fake repo --------------------------------------------------------------------


def test_the_fake_repo_has_clean_violating_unsure_and_hidden_copy():
    names = {p.relative_to(REPO).as_posix() for p in REPO.rglob("*") if p.is_file()}
    assert {
        ".brandlint.yml",
        "docs/clean.md",
        "docs/violating.md",
        "docs/unsure.md",
        "docs/drafts/skip-me.md",
        "site/hidden.html",
        "i18n/en.json",
        "i18n/en.yaml",
        "locales/en.po",
        "strings/en.properties",
        "src/app.py",
    } <= names
    assert "display:none" in (REPO / "site/hidden.html").read_text(encoding="utf-8")
    assert "Onramp" in (REPO / "docs/violating.md").read_text(encoding="utf-8")


def test_the_binary_fixtures_are_real_files(tmp_path):
    docx = build.make_docx(tmp_path / "brief.docx", ["Heading", "A paragraph."])
    png = build.make_png(tmp_path / "logo.png")
    from docx import Document
    from PIL import Image

    assert [p.text for p in Document(str(docx)).paragraphs][-1] == "A paragraph."
    assert Image.open(png).size == (4, 4)


# --- The fake GitHub ------------------------------------------------------------------


def call(base, method, path, body=None, headers=None):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read() or b"null")


def test_the_fake_github_records_comments_check_runs_and_annotations():
    with FakeGitHub() as github:
        made = call(github.url, "POST", "/repos/o/r/issues/7/comments", {"body": "first"})
        call(github.url, "PATCH", f"/repos/o/r/issues/comments/{made['id']}", {"body": "second"})
        listed = call(github.url, "GET", "/repos/o/r/issues/7/comments")
        run = call(github.url, "POST", "/repos/o/r/check-runs", {"name": "BrandLint"})
        call(
            github.url,
            "PATCH",
            f"/repos/o/r/check-runs/{run['id']}",
            {
                "conclusion": "failure",
                "output": {"title": "t", "summary": "s", "annotations": [{"path": "a.md"}]},
            },
        )
    assert [c["body"] for c in listed] == ["second"]  # updated in place, not duplicated
    assert github.comments == {7: [{"id": made["id"], "body": "second"}]}
    assert github.check_runs[0]["conclusion"] == "failure"
    assert github.annotations == [{"path": "a.md"}]


# --- The fake BrandLint server --------------------------------------------------------


def test_the_fake_server_answers_the_contract_and_records_what_it_was_sent():
    with FakeBrandLint(outcome="fail", polls_before_done=0) as server:
        denied = None
        try:
            call(server.url, "POST", "/ci/runs", {"repo": "o/r"})
        except urllib.error.HTTPError as error:
            denied = error.code
        assert denied == 401
        request = CIRunRequest(
            repo="o/r", sha="abc", files=[{"path": "a.md", "channel": "blog", "text": "x"}]
        )
        created = call(
            server.url,
            "POST",
            "/ci/runs",
            json.loads(request.model_dump_json()),
            {"Authorization": "Bearer bl_test"},
        )
        status = CIRunStatus.model_validate(
            call(server.url, "GET", f"/ci/runs/{created['id']}", headers={"Authorization": "Bearer bl_test"})
        )
    assert status.result == "fail" and status.files[0].findings
    assert server.requests[-1]["authorization"] == "Bearer bl_test"
    assert server.runs_created == 1
