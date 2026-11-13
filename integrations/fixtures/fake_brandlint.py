"""A fake BrandLint server for CLI and Action tests: it answers the CI contract on a script.

Standard library only. `outcome` picks what every run comes back as:

- `pass`: done, no findings that count;
- `fail`: done, one blocking finding (VIOLATION, high) with a link;
- `unsure`: done, one UNSURE finding, which fails by default;
- `error`: the run itself errored (for example the engine failed);
- `slow`: the run stays `running` forever, so a client has to time out;
- `down`: every request is answered 503.

It checks the bearer token (`bl_...`), records every request so a test can look at what was
sent, and reports a run only after `polls_before_done` reads, as a real review would.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from integrations.fixtures import ALLOWED_PORTS


def finding(file_path: str, kind: str) -> dict[str, Any]:
    unsure = kind == "unsure"
    return {
        "id": f"f-{file_path}-{kind}",
        "rule_id": "R-TERM-02",
        "severity": "medium" if unsure else "high",
        "verdict": "UNSURE" if unsure else "VIOLATION",
        "status": "open",
        "span": "Tarnhollow Onramp",
        "line": 3,
        "title": "Retired product name",
        "url": f"https://app.example/ci/runs/run-1#finding-f-{file_path}-{kind}",
        "blocking": True,
    }


class FakeBrandLint:
    def __init__(self, outcome: str = "pass", polls_before_done: int = 1) -> None:
        self.outcome = outcome
        self.polls_before_done = polls_before_done
        self.requests: list[dict[str, Any]] = []
        self.runs: dict[str, dict[str, Any]] = {}
        self.runs_created = 0
        self._polls: dict[str, int] = {}
        self._server: ThreadingHTTPServer | None = None

    def __enter__(self) -> FakeBrandLint:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "body": body,
                    }
                )
                status, payload = outer.route(
                    self.command, self.path, body, self.headers.get("Authorization", "")
                )
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _handle

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        ALLOWED_PORTS.add(self._server.server_address[1])
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._server:
            ALLOWED_PORTS.discard(self._server.server_address[1])
            self._server.shutdown()
            self._server.server_close()

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def route(self, method: str, path: str, body: Any, auth: str) -> tuple[int, Any]:
        if self.outcome == "down":
            return 503, {"detail": "unavailable"}
        if not auth.startswith("Bearer bl_"):
            return 401, {"detail": "Not signed in"}
        if method == "POST" and path == "/ci/runs":
            self.runs_created += 1
            run_id = f"run-{self.runs_created}"
            self.runs[run_id] = body
            return 201, self._status(run_id, done=False)
        if (match := re.fullmatch(r"/ci/runs/([\w-]+)", path)) and method == "GET":
            run_id = match.group(1)
            if run_id not in self.runs:
                return 404, {"detail": "Run not found"}
            self._polls[run_id] = self._polls.get(run_id, 0) + 1
            return 200, self._status(run_id, done=self._polls[run_id] > self.polls_before_done)
        return 404, {"detail": "Not Found"}

    def _status(self, run_id: str, *, done: bool) -> dict[str, Any]:
        files = (self.runs.get(run_id) or {}).get("files", [])
        state = "running"
        result = None
        reasons: list[str] = []
        results = []
        if self.outcome == "slow":
            done = False
        if done and self.outcome == "error":
            state, reasons = "error", ["The review didn't finish."]
        elif done:
            state = "done"
            bad = self.outcome in ("fail", "unsure")
            result = "fail" if bad else "pass"
            if bad:
                reasons = ["1 finding blocks this run."]
        for index, item in enumerate(files):
            found = []
            if done and state == "done" and self.outcome in ("fail", "unsure") and index == 0:
                found = [finding(item["path"], self.outcome)]
            results.append(
                {
                    "path": item["path"],
                    "content_id": f"c-{index}",
                    "review_id": f"r-{index}",
                    "state": state if done else "running",
                    "findings": found,
                }
            )
        return {
            "id": run_id,
            "state": state,
            "result": result,
            "reasons": reasons,
            "files": results,
            "url": f"https://app.example/ci/runs/{run_id}",
            "policy": {"severity_threshold": "medium", "fail_on_unsure": True},
        }
