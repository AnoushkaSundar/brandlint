"""What the Action tells GitHub: a job summary and one pull request comment, kept up to date.

The comment and summary show finding titles, rule ids and links, never a quoted draft. The
comment is found by a hidden marker and edited in place, so a new push never adds a second
one. Posting it needs only `pull-requests: write`, and a failure to post never fails the
check: the annotations and the exit code are the result.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

MARKER = "<!-- brandlint-ci -->"
HEADLINES = {"pass": "Passed", "fail": "Failed", "error": "Could not check", "skipped": "Not run"}


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def markdown(result: str, statuses: list[dict[str, Any]], warnings: list[str], skipped: list[Any]) -> str:
    lines = [MARKER, f"### BrandLint: {HEADLINES.get(result, result)}", ""]
    rows = []
    for status in statuses:
        for file in status.get("files", []):
            for found in file.get("findings", []):
                place = found.get("location") or {}
                line = place.get("line")
                where = f"{file['path']}:{line}" if line else file["path"]
                if place.get("key"):
                    where += f" `{place['key']}`"
                rows.append(
                    "| {} | {} | {} | {} | {} | [open]({}) |".format(
                        _cell(where),
                        found["severity"],
                        _cell(found["title"]),
                        _cell(found.get("rule_id") or "no rule"),
                        "blocks the run" if found.get("blocking") else "doesn't block",
                        found["url"],
                    )
                )
    if rows:
        lines += ["| Where | Severity | Finding | Rule | Effect | |", "|---|---|---|---|---|---|", *rows, ""]
    elif result == "pass":
        lines += ["No finding blocks this run.", ""]
    for status in statuses:
        for reason in status.get("reasons", [])[:1]:
            lines += [reason, ""]
    for path, why in skipped:
        lines.append(f"- Not checked: `{path}` ({_cell(why)})")
    for warning in warnings:
        lines.append(f"- {_cell(warning)}")
    if skipped or warnings:
        lines.append("")
    for status in statuses:
        lines.append(f"[Open the run in BrandLint]({status['url']})")
    lines += ["", "_A pass means no finding blocks the run. It is not an approval._"]
    return "\n".join(lines) + "\n"


def _request(method: str, url: str, token: str, body: dict | None = None) -> Any:
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "brandlint-action",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read() or b"null")


def upsert_comment(api: str, token: str, repo: str, pr: int, body: str) -> str:
    """Edits this tool's comment on the pull request, or adds it the first time."""
    base = f"{api.rstrip('/')}/repos/{repo}"
    existing = _request("GET", f"{base}/issues/{pr}/comments?per_page=100", token) or []
    mine = next((c for c in existing if MARKER in (c.get("body") or "")), None)
    if mine:
        _request("PATCH", f"{base}/issues/comments/{mine['id']}", token, {"body": body})
        return "updated"
    _request("POST", f"{base}/issues/{pr}/comments", token, {"body": body})
    return "created"


def try_upsert(api: str, token: str, repo: str, pr: int, body: str) -> str | None:
    try:
        return upsert_comment(api, token, repo, pr, body)
    except (urllib.error.URLError, OSError, ValueError):
        return None
