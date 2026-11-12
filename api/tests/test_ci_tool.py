"""The CI tool: what blocks a merge, what's reported, and that it fails closed."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "brandlint_ci.py"
spec = importlib.util.spec_from_file_location("brandlint_ci", SCRIPT)
ci = importlib.util.module_from_spec(spec)
sys.modules["brandlint_ci"] = ci
spec.loader.exec_module(ci)


def finding(severity="high", verdict="VIOLATION", text="best-in-class", **over):
    base = {
        "id": "f1", "severity": severity, "verdict": verdict, "check": "terminology",
        "rule_id": "R-TERM-01", "fact_ids": [], "explanation": "Banned superlative.",
        "spans": [{"chunk_id": "c0", "start": 0, "end": len(text)}],
    }
    return base | over


class Fake:
    """A BrandLint API that records what it was sent."""

    def __init__(self, findings, *, login=200, ending="done", chunk="best-in-class is here"):
        self.findings, self.login, self.ending, self.chunk = findings, login, ending, chunk
        self.seen: list[tuple[str, str, dict, bytes]] = []

    def start(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, body, kind="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def answer(self):
                size = int(self.headers.get("Content-Length") or 0)
                fake.seen.append(
                    (self.command, self.path, dict(self.headers), self.rfile.read(size))
                )
                if self.path == "/api/auth/login":
                    if fake.login != 200:
                        return self.reply(fake.login, {"detail": "Wrong email or password"})
                    return self.reply(200, {"access_token": "tok"})
                if self.headers.get("Authorization") != "Bearer tok":
                    return self.reply(401, {"detail": "Not signed in"})
                if self.path == "/api/content":
                    return self.reply(201, {"id": "c1"})
                if self.path == "/api/content/c1/reviews":
                    return self.reply(201, {"engine_review_id": "e1"})
                if self.path == "/api/engine/reviews/e1/chunks":
                    return self.reply(200, [{"id": "c0", "text": fake.chunk}])
                if self.path == "/api/engine/reviews/e1/findings":
                    body = "".join(
                        f"event: finding\ndata: {json.dumps(f)}\n\n" for f in fake.findings
                    )
                    if fake.ending:
                        body += f"event: {fake.ending}\ndata: {{}}\n\n"
                    return self.reply(200, body.encode(), "text/event-stream")
                return self.reply(404, {"detail": "nope"})

            do_GET = do_POST = answer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def stop(self):
        self.server.shutdown()

    def uploads(self):
        return [item for item in self.seen if item[1] == "/api/content"]


@pytest.fixture()
def serve():
    started = []

    def make(findings=(), **kw):
        fake = Fake(list(findings), **kw).start()
        started.append(fake)
        return fake

    yield make
    for fake in started:
        fake.stop()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "copy.md").write_text("Intro.\nOur best-in-class tool is here.\nEnd.\n")
    return tmp_path


def run(fake, *extra, files=("copy.md",)):
    return ci.main([
        *files, "--url", fake.url, "--email", "ci@x.y", "--password", "pw", *extra,
    ])


def test_a_clean_file_passes(serve, repo, capsys):
    assert run(serve()) == 0
    assert "0 blocking" in capsys.readouterr().out


def test_a_violation_blocks_and_links_to_the_review(serve, repo, capsys):
    fake = serve([finding()])
    assert run(fake) == 1
    out = capsys.readouterr().out
    assert f"{fake.url}/content/c1/review" in out
    assert "Banned superlative." in out
    assert "R-TERM-01" in out


@pytest.mark.parametrize(
    ("severity", "fail_on", "expected"),
    [("high", "medium", 1), ("high", "high", 1), ("medium", "high", 0),
     ("low", "low", 1), ("critical", "critical", 1), ("high", "critical", 0)],
)
def test_the_threshold_decides_what_blocks(serve, repo, severity, fail_on, expected):
    assert run(serve([finding(severity)]), "--fail-on", fail_on) == expected


def test_unsure_blocks_by_default_because_a_person_has_to_look(serve, repo):
    assert run(serve([finding("low", "UNSURE")])) == 1


def test_unsure_can_be_a_warning_when_asked(serve, repo):
    assert run(serve([finding("critical", "UNSURE")]), "--unsure", "warn") == 0


def test_a_passing_finding_never_blocks(serve, repo):
    assert run(serve([finding("critical", "PASS")])) == 0


def test_the_line_comes_from_the_flagged_words(serve, repo, capsys):
    assert run(serve([finding()])) == 1
    assert "line 2:" in capsys.readouterr().out


def test_github_annotations_carry_file_line_and_link(serve, repo, capsys):
    fake = serve([finding(explanation="Bad.\nVery bad.")])
    run(fake, "--github")
    out = capsys.readouterr().out
    assert "::error file=copy.md,line=2,title=BrandLint R-TERM-01::" in out
    assert "Bad.%0AVery bad." in out
    assert "/content/c1/review" in out


def test_a_non_blocking_finding_is_a_warning(serve, repo, capsys):
    run(serve([finding("low")]), "--github", "--fail-on", "high")
    assert "::warning file=copy.md,line=2" in capsys.readouterr().out


def test_the_job_summary_says_a_pass_is_not_an_approval(serve, repo, monkeypatch):
    summary = repo / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    run(serve([finding()]))
    text = summary.read_text(encoding="utf-8")
    assert "open the review" in text
    assert "isn't an approval" in text


def test_it_signs_in_and_sends_what_it_was_asked(serve, repo):
    fake = serve()
    run(fake, "--channel", "blog", "--data-class", "confidential")
    _, _, headers, body = fake.uploads()[0]
    assert headers["Authorization"] == "Bearer tok"
    assert b'name="channel"\r\n\r\nblog' in body
    assert b'name="data_class"\r\n\r\nconfidential' in body
    assert b'name="source"\r\n\r\nci' in body
    assert b"best-in-class tool" in body


def test_internal_is_the_default_data_class(serve, repo):
    fake = serve()
    run(fake)
    assert b'name="data_class"\r\n\r\ninternal' in fake.uploads()[0][3]


def test_a_failed_sign_in_fails_closed(serve, repo):
    assert run(serve(login=401)) == 2


def test_an_unreachable_server_fails_closed(repo):
    code = ci.main(["copy.md", "--url", "http://127.0.0.1:9", "--email", "a", "--password", "b"])
    assert code == 2


def test_on_error_warn_lets_an_outage_through_but_says_so(serve, repo, capsys):
    fake = serve(ending="error")
    assert run(fake, "--on-error", "warn") == 0
    assert "ERROR" in capsys.readouterr().out


def test_a_review_that_errors_is_never_a_pass(serve, repo):
    assert run(serve([finding("low")], ending="error"), "--fail-on", "critical") == 2


def test_a_stream_that_just_stops_is_never_a_pass(serve, repo):
    assert run(serve([], ending="")) == 2


def test_too_many_files_is_an_error_not_a_silent_partial_check(serve, repo):
    names = []
    for number in range(4):
        (repo / f"n{number}.md").write_text("Words here.")
        names.append(f"n{number}.md")
    assert run(serve(), "--max-files", "3", files=names) == 2


def test_other_file_types_are_skipped_and_reported(serve, repo, capsys):
    (repo / "image.png").write_bytes(b"x")
    (repo / "code.py").write_text("x = 1")
    assert run(serve(), files=("image.png", "code.py")) == 0
    out = capsys.readouterr().out
    assert "No copy files to check." in out
    assert "image.png: not a copy file type" in out


def test_empty_and_missing_files_are_skipped_and_reported(serve, repo, capsys):
    (repo / "empty.md").write_text("")
    run(serve(), files=("empty.md", "gone.md"))
    out = capsys.readouterr().out
    assert "empty.md: empty" in out
    assert "gone.md: not found" in out


def test_include_and_exclude_patterns(repo):
    for name in ("docs/a.md", "docs/b.md", "top.md"):
        path = repo / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("Words here.")
    chosen, skipped = ci.select(
        ["docs/a.md", "docs/b.md", "top.md"], ["**/*.md"], ["docs/b.md"]
    )
    assert chosen == ["docs/a.md", "top.md"]
    assert skipped == ["docs/b.md: excluded"]


def test_a_missing_setting_is_a_usage_error(repo, monkeypatch):
    for name in ("BRANDLINT_URL", "BRANDLINT_EMAIL", "BRANDLINT_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert ci.main(["copy.md"]) == 2


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_only_changed_files_are_checked(serve, repo):
    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")
    git("add", "copy.md")
    git("commit", "-qm", "base")
    (repo / "new.md").write_text("A new page of words.")
    (repo / "notes.py").write_text("x = 1")
    git("checkout", "-qb", "feature")
    git("add", "new.md", "notes.py")
    git("commit", "-qm", "change")
    fake = serve()
    code = ci.main([
        "--changed-since", "main", "--url", fake.url, "--email", "a", "--password", "b",
    ])
    assert code == 0
    sent = [item for item in fake.uploads()]
    assert len(sent) == 1
    assert b"A new page of words." in sent[0][3]
