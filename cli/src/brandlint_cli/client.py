"""Talking to the BrandLint server. The token is only ever in the Authorization header,
and is masked in everything the tool prints."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx

TOKEN_PATTERN = re.compile(r"bl_[A-Za-z0-9_\-]{6,}")


class ServerError(Exception):
    """BrandLint could not be reached, or answered with an error. Maps through --on-error."""


class Masker:
    def __init__(self, token: str = "") -> None:
        self.token = token

    def __call__(self, text: str) -> str:
        if self.token:
            text = text.replace(self.token, "bl_***")
        return TOKEN_PATTERN.sub("bl_***", text)


class Client:
    def __init__(self, server: str, token: str, timeout: float = 30.0, transport: Any = None) -> None:
        self.mask = Masker(token)
        self._http = httpx.Client(
            base_url=server.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "User-Agent": "brandlint-cli"},
            timeout=timeout,
            transport=transport,
        )

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise ServerError(self.mask(f"Could not reach BrandLint: {type(error).__name__}")) from None
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            hint = {401: " Check BRANDLINT_TOKEN.", 403: " That workspace can not be used right now."}.get(
                response.status_code, ""
            )
            raise ServerError(
                self.mask(f"BrandLint answered {response.status_code}: {detail or response.reason_phrase}.{hint}")
            )
        try:
            return response.json()
        except ValueError:
            raise ServerError("BrandLint answered with something that is not JSON.") from None

    def submit(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/ci/runs", json=body)

    def run(self, run_id: str) -> dict[str, Any]:
        return self._call("GET", f"/ci/runs/{run_id}")

    def wait(
        self,
        run_id: str,
        timeout: float,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        first: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Polls with a growing pause until the run is done or errored, or `timeout` passes."""
        deadline = clock() + timeout
        pause = 1.0
        status = first
        while True:
            if status is None:
                status = self.run(run_id)
            if status["state"] in ("done", "error"):
                return status
            if clock() >= deadline:
                raise ServerError(
                    "BrandLint did not finish in time, so the run can not say whether this passes."
                )
            sleep(pause)
            pause = min(pause * 1.5, 5.0)
            status = None
