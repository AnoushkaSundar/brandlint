"""A fake GitHub API for tests: it records PR comments, check runs and annotations.

Standard library only, so the Action's reporting scripts and the CLI tests can run against
it without the network. It speaks just enough of the REST API: issue comments (list, create,
update) and check runs (create, update).
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from integrations.fixtures import ALLOWED_PORTS


class FakeGitHub:
    def __init__(self) -> None:
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.check_runs: list[dict[str, Any]] = []
        self.annotations: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self._next_id = 100
        self._server: ThreadingHTTPServer | None = None

    # --- lifecycle -------------------------------------------------------------------

    def __enter__(self) -> FakeGitHub:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # keep test output quiet
                pass

            def _read(self) -> Any:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"null") if length else None

            def _send(self, status: int, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self) -> None:
                body = self._read()
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "body": body,
                    }
                )
                status, payload = outer.route(self.command, self.path, body)
                self._send(status, payload)

            do_GET = do_POST = do_PATCH = _handle

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        ALLOWED_PORTS.add(self._server.server_address[1])
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server:
            ALLOWED_PORTS.discard(self._server.server_address[1])
            self._server.shutdown()
            self._server.server_close()

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    # --- the API ---------------------------------------------------------------------

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def route(self, method: str, path: str, body: Any) -> tuple[int, Any]:
        if match := re.fullmatch(r"/repos/[^/]+/[^/]+/issues/(\d+)/comments", path):
            number = int(match.group(1))
            if method == "GET":
                return 200, self.comments.get(number, [])
            if method == "POST":
                comment = {"id": self._new_id(), "body": body["body"]}
                self.comments.setdefault(number, []).append(comment)
                return 201, comment
        if match := re.fullmatch(r"/repos/[^/]+/[^/]+/issues/comments/(\d+)", path):
            comment_id = int(match.group(1))
            for comments in self.comments.values():
                for comment in comments:
                    if comment["id"] == comment_id and method == "PATCH":
                        comment["body"] = body["body"]
                        return 200, comment
            return 404, {"message": "Not Found"}
        if re.fullmatch(r"/repos/[^/]+/[^/]+/check-runs", path) and method == "POST":
            run = {"id": self._new_id(), **(body or {})}
            self.check_runs.append(run)
            return 201, run
        if match := re.fullmatch(r"/repos/[^/]+/[^/]+/check-runs/(\d+)", path):
            if method == "PATCH":
                for run in self.check_runs:
                    if run["id"] == int(match.group(1)):
                        run.update(body or {})
                        self.annotations.extend((body or {}).get("output", {}).get("annotations", []))
                        return 200, run
            return 404, {"message": "Not Found"}
        return 404, {"message": "Not Found"}
