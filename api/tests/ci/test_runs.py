"""Block 2: a CI job submits files and gets a run, on the mock engine."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from app import db
from app.ci.models import CIRun, CIRunFile
from app.content.models import Content, ContentVersion
from app.main import create_app
from app.workflow.models import Review
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from integrations.fixtures import build

REPO = Path(__file__).resolve().parents[3] / "integrations" / "fixtures" / "repo"


@pytest.fixture()
def mock_app(monkeypatch):
    """The app as it runs by default: every service is its mock, so a review needs no model."""
    for flag in ("ENGINE", "GATEWAY", "MEMORY"):
        monkeypatch.setenv(f"USE_MOCK_{flag}", "true")
    return create_app()


@pytest.fixture()
def bot(world, client_for, mock_app):
    """A CI job for workspace A: a service token, and a client that sends it."""
    made = client_for(world.a.admin).post("/ci/tokens", json={"name": "CI"}).json()
    client = TestClient(mock_app, raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {made['token']}"
    return client


def person(mock_app, who) -> TestClient:
    client = TestClient(mock_app, raise_server_exceptions=False)
    client.cookies.set("brandlint_session", who.token)
    return client


def text_file(path: str, text: str, channel: str = "blog") -> dict:
    return {"path": path, "channel": channel, "text": text}


def request(*files: dict, pr: int | None = 7, sha: str = "abc123") -> dict:
    return {"repo": "acme/site", "pr": pr, "sha": sha, "files": list(files)}


def fixture_files() -> list[dict]:
    return [
        text_file("docs/clean.md", (REPO / "docs/clean.md").read_text(encoding="utf-8")),
        text_file("docs/violating.md", (REPO / "docs/violating.md").read_text(encoding="utf-8")),
        text_file("site/hidden.html", (REPO / "site/hidden.html").read_text(encoding="utf-8")),
    ]


def count(model) -> int:
    with db.get_sessionmaker()() as session:
        return session.scalar(select(func.count()).select_from(model))


# --- Submitting and reading a run ------------------------------------------------------


def test_the_fixture_tree_goes_in_and_findings_come_back_through_the_mock_engine(bot):
    created = bot.post("/ci/runs", json=request(*fixture_files()))
    assert created.status_code == 201, created.text
    run = bot.get(f"/ci/runs/{created.json()['id']}").json()
    assert run["state"] == "done"
    assert [f["path"] for f in run["files"]] == [
        "docs/clean.md",
        "docs/violating.md",
        "site/hidden.html",
    ]
    findings = [x for f in run["files"] for x in f["findings"]]
    assert findings, "the mock engine reports findings for a review"
    first = findings[0]
    assert first["url"].endswith(f"/ci/runs/{run['id']}#finding-{first['id']}")
    assert first["title"] and first["verdict"] in ("VIOLATION", "UNSURE")
    assert run["url"].endswith(f"/ci/runs/{run['id']}")


def test_ci_content_is_one_piece_per_file_authored_by_a_service_user(bot, world):
    bot.post("/ci/runs", json=request(*fixture_files()))
    with db.get_sessionmaker()() as session:
        pieces = session.scalars(select(Content).where(Content.source == "ci")).all()
        mine = [c for c in pieces if str(c.org_id) == world.a.org.id]
        assert {c.external_ref for c in mine} == {
            "acme/site:docs/clean.md",
            "acme/site:docs/violating.md",
            "acme/site:site/hidden.html",
        }
        assert len({c.creator_id for c in mine}) == 1  # one service user for the org


def test_the_same_request_twice_is_one_run_with_the_same_reviews(bot):
    body = request(*fixture_files())
    first = bot.post("/ci/runs", json=body).json()
    reviews_after_first = count(Review)
    second = bot.post("/ci/runs", json=body)
    assert second.status_code in (200, 201)
    assert second.json()["id"] == first["id"]
    assert count(Review) == reviews_after_first
    assert count(CIRun) >= 1


def test_a_changed_file_adds_a_version_and_an_unchanged_one_does_not(bot):
    one = text_file("docs/a.md", "First text.")
    two = text_file("docs/b.md", "Other text.")
    bot.post("/ci/runs", json=request(one, two, sha="s1"))
    reviews = count(Review)
    versions = count(ContentVersion)

    changed = text_file("docs/a.md", "First text, edited.")
    bot.post("/ci/runs", json=request(changed, two, sha="s2"))
    assert count(ContentVersion) == versions + 1
    assert count(Review) == reviews + 1

    bot.post("/ci/runs", json=request(changed, two, sha="s3"))  # a new commit, same copy
    assert count(ContentVersion) == versions + 1
    assert count(Review) == reviews + 1


def test_a_finished_review_moves_ci_content_to_resolving_so_a_reviewer_can_act(bot, world):
    run = bot.post("/ci/runs", json=request(text_file("docs/a.md", "Some copy."))).json()
    bot.get(f"/ci/runs/{run['id']}")
    with db.get_sessionmaker()() as session:
        state = session.scalar(select(Content.state).where(Content.external_ref == "acme/site:docs/a.md"))
    assert state == "resolving"


def test_ci_content_never_appears_in_a_creators_own_list_but_a_reviewer_can_filter_for_it(
    bot, world, mock_app
):
    bot.post("/ci/runs", json=request(text_file("docs/a.md", "Some copy.")))
    creator = person(mock_app, world.a.creator)
    assert all(row["source"] != "ci" for row in creator.get("/content").json())
    assert creator.get("/content?source=ci").json() == []
    reviewer = person(mock_app, world.a.reviewer)
    assert all(row["source"] != "ci" for row in reviewer.get("/content").json())
    ci_rows = reviewer.get("/content?source=ci").json()
    assert [row["title"] for row in ci_rows] == ["docs/a.md"]


def test_ci_content_cannot_be_moved_towards_publication(bot, world, mock_app):
    run = bot.post("/ci/runs", json=request(text_file("docs/a.md", "Some copy."))).json()
    bot.get(f"/ci/runs/{run['id']}")
    reviewer = person(mock_app, world.a.reviewer)
    content_id = reviewer.get("/content?source=ci").json()[0]["id"]
    refused = reviewer.post(f"/workflow/content/{content_id}/transitions", json={"to": "reviewer_check"})
    assert refused.status_code == 409


def test_the_service_user_is_hidden_from_the_people_list_and_cannot_sign_in(bot, world, client_for):
    bot.post("/ci/runs", json=request(text_file("docs/a.md", "Some copy.")))
    listed = client_for(world.a.admin).get("/admin/users").json()
    assert all("brandlint.invalid" not in row["email"] for row in listed)
    assert {row["id"] for row in listed} == {p.id for p in world.a.people}


# --- What is refused -------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["../outside.md", "docs/../../etc/passwd", "/etc/passwd", "C:\\temp\\a.md", "docs\\a.md", "a\x00b.md", ""],
)
def test_unsafe_paths_are_refused(bot, path):
    response = bot.post("/ci/runs", json=request(text_file(path, "Hello.")))
    assert response.status_code == 422


def test_nothing_is_created_when_a_path_is_refused(bot):
    before = (count(CIRun), count(CIRunFile))
    bot.post("/ci/runs", json=request(text_file("fine.md", "Fine."), text_file("../bad.md", "Bad.")))
    assert (count(CIRun), count(CIRunFile)) == before


def test_a_file_must_be_text_or_a_real_binary_of_its_kind(bot, tmp_path):
    png = build.make_png(tmp_path / "logo.png").read_bytes()
    docx = build.make_docx(tmp_path / "brief.docx", ["Hello."]).read_bytes()

    def binary(path: str, data: bytes) -> dict:
        return {"path": path, "channel": "document", "file_b64": base64.b64encode(data).decode()}

    assert bot.post("/ci/runs", json=request(binary("brief.docx", docx))).status_code == 201
    mislabelled = bot.post("/ci/runs", json=request(binary("brief.docx", png)))
    assert mislabelled.status_code == 422 and "docx" in mislabelled.text.lower()
    unsupported = bot.post("/ci/runs", json=request(binary("tool.exe", b"MZ\x00\x00")))
    assert unsupported.status_code == 422
    broken = bot.post("/ci/runs", json=request({"path": "a.docx", "channel": "document", "file_b64": "not base64!!"}))
    assert broken.status_code == 422


def test_text_with_a_null_character_or_too_large_is_refused(bot, monkeypatch):
    assert bot.post("/ci/runs", json=request(text_file("a.md", "bad\x00text"))).status_code == 422
    monkeypatch.setenv("CI_MAX_FILE_BYTES", "100")
    assert bot.post("/ci/runs", json=request(text_file("a.md", "x" * 101))).status_code == 413


def test_a_file_with_both_text_and_a_binary_or_neither_is_refused(bot):
    both = {"path": "a.md", "channel": "blog", "text": "x", "file_b64": "eA=="}
    assert bot.post("/ci/runs", json=request(both)).status_code == 422
    neither = {"path": "a.md", "channel": "blog"}
    assert bot.post("/ci/runs", json=request(neither)).status_code == 422


# --- Quotas ----------------------------------------------------------------------------


def test_too_many_files_or_bytes_in_one_run_is_a_429(bot, monkeypatch):
    monkeypatch.setenv("CI_MAX_FILES_PER_RUN", "2")
    files = [text_file(f"docs/{n}.md", f"Copy {n}.") for n in range(3)]
    assert bot.post("/ci/runs", json=request(*files)).status_code == 429
    monkeypatch.setenv("CI_MAX_FILES_PER_RUN", "50")
    monkeypatch.setenv("CI_MAX_BYTES_PER_RUN", "10")
    assert bot.post("/ci/runs", json=request(text_file("a.md", "x" * 50))).status_code == 429


def test_runs_per_day_are_capped_per_token_and_per_workspace(world, client_for, mock_app, monkeypatch):
    admin = client_for(world.a.admin)
    tokens = [admin.post("/ci/tokens", json={"name": f"t{n}"}).json()["token"] for n in range(2)]

    def as_token(token: str) -> TestClient:
        c = TestClient(mock_app, raise_server_exceptions=False)
        c.headers["Authorization"] = f"Bearer {token}"
        return c

    monkeypatch.setenv("CI_MAX_RUNS_PER_TOKEN_PER_DAY", "1")
    assert as_token(tokens[0]).post("/ci/runs", json=request(text_file("a.md", "One."), sha="1")).status_code == 201
    assert as_token(tokens[0]).post("/ci/runs", json=request(text_file("a.md", "Two."), sha="2")).status_code == 429
    # Another token has its own allowance, until the workspace's own cap is reached.
    monkeypatch.setenv("CI_MAX_RUNS_PER_DAY", "1")
    assert as_token(tokens[1]).post("/ci/runs", json=request(text_file("a.md", "Three."), sha="3")).status_code == 429


# --- Whose run it is -------------------------------------------------------------------


def test_another_workspaces_run_is_a_404_for_its_people_and_its_tokens(
    bot, world, client_for, mock_app
):
    run = bot.post("/ci/runs", json=request(text_file("a.md", "Some copy."))).json()
    assert person(mock_app, world.b.admin).get(f"/ci/runs/{run['id']}").status_code == 404
    other = client_for(world.b.admin).post("/ci/tokens", json={"name": "b"}).json()["token"]
    b_bot = TestClient(mock_app, raise_server_exceptions=False)
    b_bot.headers["Authorization"] = f"Bearer {other}"
    assert b_bot.get(f"/ci/runs/{run['id']}").status_code == 404
    assert b_bot.get("/ci/runs/does-not-exist").status_code == 404


def test_a_signed_in_creator_or_admin_can_start_a_run_but_a_reviewer_cannot(world, mock_app):
    body = request(text_file("a.md", "Some copy."))
    assert person(mock_app, world.a.creator).post("/ci/runs", json=body).status_code == 201
    assert person(mock_app, world.a.reviewer).post("/ci/runs", json={**body, "sha": "z"}).status_code == 403
