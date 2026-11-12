#!/usr/bin/env python3
"""BrandLint for CI and pre-commit: review copy files before they merge.

Each file goes through the real review engine, as if a creator had uploaded it. The
run fails (exit 1) if any finding is serious enough, and prints a link to the review
page, where a person can read the finding, see why it was flagged, and decide.

Nothing here approves, fixes or overrides anything. Only the signed-in people in the
BrandLint app can do that. A passing run means "no blocking findings", not "approved".

Standard library only, so a CI runner needs nothing installed.

Exit codes: 0 passed, 1 blocked by a finding, 2 couldn't check (fails closed).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

SEVERITIES = ["low", "medium", "high", "critical"]
SUPPORTED = {".md", ".txt", ".html", ".htm", ".docx", ".pdf"}
DEFAULT_PATTERNS = ["**/*.md", "**/*.txt", "**/*.html", "**/*.htm", "**/*.docx"]
MAX_BYTES = 5 * 1024 * 1024
CHANNELS = ["blog", "linkedin", "email", "ad", "banner", "document"]
DATA_CLASSES = ["public", "internal", "confidential", "restricted"]


class CheckError(Exception):
    """BrandLint couldn't check a file. Never treated as a pass."""


@dataclass
class Result:
    path: str
    content_id: str = ""
    findings: list[dict] = field(default_factory=list)
    lines: dict[str, int] = field(default_factory=dict)
    blocking: list[dict] = field(default_factory=list)
    error: str = ""


class Client:
    def __init__(self, api: str, timeout: float):
        self.api = api.rstrip("/")
        self.timeout = timeout
        self.token = ""

    def request(self, method, path, body=None, content_type=None, stream=False):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(
            self.api + path, data=body, method=method, headers=headers
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            try:
                detail = json.loads(detail).get("detail", detail)
            except (ValueError, AttributeError):
                pass
            raise CheckError(f"{method} {path} -> {error.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise CheckError(f"couldn't reach {self.api}: {error}") from None
        if stream:
            return response
        with response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def login(self, email: str, password: str) -> None:
        reply = self.request(
            "POST",
            "/auth/login",
            json.dumps({"email": email, "password": password}).encode(),
            "application/json",
        )
        self.token = reply["access_token"]


def multipart(fields: dict[str, str], filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = b""
    for key, value in fields.items():
        parts += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
            f"\r\n\r\n{value}\r\n"
        ).encode()
    parts += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode() + data + b"\r\n"
    parts += f"--{boundary}--\r\n".encode()
    return parts, f"multipart/form-data; boundary={boundary}"


def matches(path: str, patterns: list[str]) -> bool:
    """fnmatch, where `**/x` also matches `x` at the top of the repo."""
    path = path.replace("\\", "/")
    return any(
        fnmatch.fnmatch(path, pattern)
        or (pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]))
        for pattern in patterns
    )


def changed_files(base: str) -> list[str]:
    """Files added, copied, modified or renamed since `base`. Deleted ones are gone."""
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode != 0:
        raise CheckError(f"git diff against {base} failed: {diff.stderr.strip()[:200]}")
    return [line for line in diff.stdout.splitlines() if line.strip()]


def select(
    paths: list[str], include: list[str], exclude: list[str]
) -> tuple[list[str], list[str]]:
    """(files to check, files skipped and why). Skipping is always reported."""
    chosen, skipped = [], []
    for path in dict.fromkeys(paths):
        if Path(path).suffix.lower() not in SUPPORTED:
            skipped.append(f"{path}: not a copy file type")
        elif include and not matches(path, include):
            skipped.append(f"{path}: not in the paths to check")
        elif exclude and matches(path, exclude):
            skipped.append(f"{path}: excluded")
        elif not Path(path).is_file():
            skipped.append(f"{path}: not found")
        elif Path(path).stat().st_size == 0:
            skipped.append(f"{path}: empty")
        elif Path(path).stat().st_size > MAX_BYTES:
            skipped.append(f"{path}: over {MAX_BYTES // 1024 // 1024} MB")
        else:
            chosen.append(path)
    return chosen, skipped


def blocks(finding: dict, fail_on: str, unsure: str) -> bool:
    """Whether a finding stops the merge. A violation at or above the threshold does.
    A finding the AI wasn't sure about does too, unless told otherwise: UNSURE means a
    person has to look, and CI can't pretend they already did."""
    if finding.get("verdict") == "UNSURE":
        return unsure == "fail"
    if finding.get("verdict") != "VIOLATION":
        return False
    return SEVERITIES.index(finding["severity"]) >= SEVERITIES.index(fail_on)


def collect(client: Client, engine_id: str, deadline: float) -> list[dict]:
    """The review's findings, once its stream says it's done."""
    response = client.request("GET", f"/engine/reviews/{engine_id}/findings", stream=True)
    findings, event = [], None
    with response:
        for raw in response:
            if time.monotonic() > deadline:
                raise CheckError("the review didn't finish in time")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
                if event == "done":
                    return findings
                if event == "error":
                    raise CheckError("the review couldn't finish")
            elif line.startswith("data:") and event == "finding":
                findings.append(json.loads(line[5:]))
    raise CheckError("the review stream ended before it finished")


def line_of(finding: dict, chunks: dict[str, str], source: str) -> int:
    """Best-effort line for a finding: the flagged words, found in the source file."""
    for span in finding.get("spans", []):
        text = chunks.get(span["chunk_id"], "")
        snippet = text[span["start"] : span["end"]].strip()
        for needle in (snippet, snippet[:40]):
            if len(needle) >= 4 and needle in source:
                return source[: source.index(needle)].count("\n") + 1
    return 1


def check_file(client: Client, path: str, args, deadline: float) -> Result:
    result = Result(path)
    data = Path(path).read_bytes()
    suffix = Path(path).suffix.lower()
    fields = {
        "title": f"CI: {path}"[:200],
        "channel": args.channel,
        "source": "ci",
        "data_class": args.data_class,
    }
    body, content_type = multipart(fields, f"copy{suffix}", data)
    created = client.request("POST", "/content", body, content_type)
    result.content_id = created["id"]
    review = client.request("POST", f"/content/{result.content_id}/reviews")
    engine_id = review["engine_review_id"]
    result.findings = collect(client, engine_id, deadline)
    chunks = {}
    try:
        chunks = {c["id"]: c["text"] for c in client.request(
            "GET", f"/engine/reviews/{engine_id}/chunks")}
    except CheckError:
        pass  # Line numbers are a courtesy. The findings stand without them.
    source = data.decode("utf-8", "replace") if suffix in {".md", ".txt", ".html", ".htm"} else ""
    result.lines = {f["id"]: line_of(f, chunks, source) for f in result.findings}
    result.blocking = [f for f in result.findings if blocks(f, args.fail_on, args.unsure)]
    return result


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def label(finding: dict) -> str:
    source = finding.get("rule_id") or ", ".join(finding.get("fact_ids", [])) or "?"
    return f"{finding['severity']} · {finding['check']} · {source}"


def report(results: list[Result], site: str, skipped: list[str], args) -> str:
    """Prints the run, and returns the Markdown for a GitHub job summary."""
    github = args.github or os.environ.get("GITHUB_ACTIONS") == "true"
    md = ["## BrandLint", ""]
    for result in results:
        link = f"{site}/content/{result.content_id}/review" if result.content_id else ""
        if result.error:
            print(f"ERROR  {result.path}: {result.error}")
            md.append(f"- ⚠️ `{result.path}`: could not be checked ({result.error})")
            if github:
                print(f"::error file={result.path},title=BrandLint could not check this::"
                      + escape(result.error))
            continue
        status = "BLOCKED" if result.blocking else "ok"
        print(f"{status:8}{result.path}: {len(result.findings)} findings, "
              f"{len(result.blocking)} blocking")
        md.append(f"- {'❌' if result.blocking else '✅'} `{result.path}`: "
                  f"{len(result.findings)} findings, {len(result.blocking)} blocking"
                  + (f" · [open the review]({link})" if link else ""))
        for finding in result.findings:
            blocking = finding in result.blocking
            line = result.lines.get(finding["id"], 1)
            print(f"  {'BLOCK' if blocking else 'note '} line {line}: [{label(finding)}] "
                  f"{finding['explanation']}")
            if blocking:
                md.append(f"  - `{label(finding)}` (line {line}): {finding['explanation']}")
                if github:
                    print(f"::error file={result.path},line={line},title=BrandLint "
                          f"{finding.get('rule_id') or 'finding'}::"
                          + escape(f"{finding['explanation']} See {link}"))
            elif github:
                print(f"::warning file={result.path},line={line},title=BrandLint "
                      f"{finding.get('rule_id') or 'note'}::" + escape(finding["explanation"]))
        if link:
            print(f"       review: {link}")
    for item in skipped:
        print(f"skip   {item}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("\n".join(md) + "\n\n")
            out.write("_A passing run means no blocking findings. It isn't an approval: "
                      "people approve in BrandLint._\n")
    return "\n".join(md)


def parse(argv: list[str] | None) -> argparse.Namespace:
    env = os.environ.get
    parser = argparse.ArgumentParser(description="Review copy files with BrandLint.")
    parser.add_argument("files", nargs="*", help="files to check (pre-commit passes these)")
    parser.add_argument("--url", default=env("BRANDLINT_URL", ""), help="the BrandLint site")
    parser.add_argument("--api-url", default=env("BRANDLINT_API_URL", ""),
                        help="the API, if not <url>/api")
    parser.add_argument("--email", default=env("BRANDLINT_EMAIL", ""))
    parser.add_argument("--password", default=env("BRANDLINT_PASSWORD", ""))
    parser.add_argument("--changed-since", metavar="REF", help="check files changed since REF")
    parser.add_argument("--include", action="append", default=[], help="glob to check")
    parser.add_argument("--exclude", action="append", default=[], help="glob to skip")
    parser.add_argument("--channel", default=env("BRANDLINT_CHANNEL", "document"), choices=CHANNELS)
    parser.add_argument("--data-class", default=env("BRANDLINT_DATA_CLASS", "internal"),
                        choices=DATA_CLASSES)
    parser.add_argument("--fail-on", default=env("BRANDLINT_FAIL_ON", "low"), choices=SEVERITIES,
                        help="block on violations at or above this severity")
    parser.add_argument("--unsure", default=env("BRANDLINT_UNSURE", "fail"),
                        choices=["fail", "warn"], help="what an UNSURE finding does")
    parser.add_argument("--on-error", default="fail", choices=["fail", "warn"],
                        help="if BrandLint can't check a file")
    parser.add_argument("--max-files", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=240, help="seconds per file")
    parser.add_argument("--github", action="store_true", help="always print GitHub annotations")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    if not (args.url or args.api_url) or not args.email or not args.password:
        print("Set BRANDLINT_URL, BRANDLINT_EMAIL and BRANDLINT_PASSWORD.", file=sys.stderr)
        return 2
    site = (args.url or args.api_url).rstrip("/")
    api = (args.api_url or f"{site}/api").rstrip("/")
    try:
        paths = list(args.files)
        if args.changed_since:
            paths += changed_files(args.changed_since)
    except CheckError as error:
        print(f"ERROR  {error}", file=sys.stderr)
        return 2
    include = args.include or (DEFAULT_PATTERNS if args.changed_since else [])
    files, skipped = select(paths, include, args.exclude)
    if len(files) > args.max_files:
        print(f"ERROR  {len(files)} files to check, over the limit of {args.max_files}. "
              "Raise --max-files, or narrow --include.", file=sys.stderr)
        return 2
    if not files:
        for item in skipped:
            print(f"skip   {item}")
        print("No copy files to check.")
        return 0

    client = Client(api, timeout=60)
    results: list[Result] = []
    try:
        client.login(args.email, args.password)
    except CheckError as error:
        print(f"ERROR  sign-in failed: {error}", file=sys.stderr)
        return 0 if args.on_error == "warn" else 2
    for path in files:
        try:
            results.append(check_file(client, path, args, time.monotonic() + args.timeout))
        except CheckError as error:
            results.append(Result(path, error=str(error)))
    report(results, site, skipped, args)

    if any(result.blocking for result in results):
        print("\nBlocked: open the review links, then fix the copy or ask a reviewer.")
        return 1
    if any(result.error for result in results):
        return 0 if args.on_error == "warn" else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
