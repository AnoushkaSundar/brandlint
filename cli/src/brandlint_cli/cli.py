"""`brandlint check`: send a repo's copy to BrandLint and exit with what it says.

Exit codes: 0 passed, 1 a finding blocks, 2 a config or usage error, 3 BrandLint could not
be reached or errored (changed by --on-error). The token comes from BRANDLINT_TOKEN only:
a flag would land in shell history and process lists.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from brandlint_cli import __version__, git, output
from brandlint_cli.client import Client, Masker, ServerError
from brandlint_cli.config import CONFIG_NAME, ConfigError, load
from brandlint_cli.discover import UsageError, discover, payload
from brandlint_cli.extract import Extracted, ExtractionError, extract

BATCH_FILES = 25
BATCH_BYTES = 8 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brandlint", description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", action="version", version=f"brandlint-cli {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check the copy in this repo")
    check.add_argument("paths", nargs="*", help="files or folders to check (default: all that the config matches)")
    check.add_argument("--changed-against", metavar="REF", help="only files changed since this git ref")
    check.add_argument("--staged", action="store_true", help="only files staged for commit")
    check.add_argument("--format", choices=["text", "json", "github", "sarif"], default="text")
    check.add_argument("--on-error", choices=["fail", "pass", "warn"], default="fail",
                       help="what to do when BrandLint can not be reached (default: fail)")
    check.add_argument("--config", help=f"path to the config (default: {CONFIG_NAME} in the repo root)")
    check.add_argument("--server", help="BrandLint API address (or BRANDLINT_SERVER, or the config)")
    check.add_argument("--root", default=".", help="the repo root (default: the current folder)")
    check.add_argument("--timeout", type=float, default=600.0, help="seconds to wait for a review")
    check.add_argument("--repo", help="repo name, as owner/name (default: GITHUB_REPOSITORY)")
    check.add_argument("--pr", type=int, help="pull request number (default: from GITHUB_REF)")
    check.add_argument("--sha", help="commit (default: GITHUB_SHA or git HEAD)")
    check.add_argument("--base-sha", help="the base commit of the pull request")
    return parser


def _batches(files: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for item in files:
        weight = len(item.get("text") or item.get("file_b64") or "")
        if current and (len(current) >= BATCH_FILES or size + weight > BATCH_BYTES):
            batches.append(current)
            current, size = [], 0
        current.append(item)
        size += weight
    if current:
        batches.append(current)
    return batches


def _head(root: Path) -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, check=False
        )
        return done.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def _pr_from(env: Mapping[str, str]) -> int | None:
    match = re.match(r"refs/pull/(\d+)/", env.get("GITHUB_REF", ""))
    return int(match.group(1)) if match else None


def run_check(
    args: argparse.Namespace,
    env: Mapping[str, str],
    out: TextIO,
    err: TextIO,
    sleep: Callable[[float], None] = time.sleep,
    transport: Any = None,
) -> int:
    token = env.get("BRANDLINT_TOKEN", "")
    mask = Masker(token)
    root = Path(args.root).resolve()

    try:
        if args.staged and args.changed_against:
            raise UsageError("Use --staged or --changed-against, not both.")
        config = load(Path(args.config) if args.config else root / CONFIG_NAME)
        only = None
        if args.staged:
            only = git.staged(root)
        elif args.changed_against:
            only = git.changed_against(root, args.changed_against)
        found = discover(root, config, args.paths or None, only)
    except (ConfigError, UsageError) as error:
        err.write(mask(f"brandlint: {error}") + "\n")
        return 2

    warnings: list[str] = []
    files: list[dict[str, Any]] = []
    extractions: dict[str, Extracted] = {}
    for candidate in found.files:
        item, why = payload(candidate)
        if item is None:
            found.skipped.append((candidate.path, why or "could not be read"))
            continue
        if "text" in item:
            try:
                extracted = extract(candidate.rule.extract, item["text"])
            except ExtractionError as error:
                found.skipped.append((candidate.path, str(error)))
                continue
            if not extracted.segments:
                found.skipped.append((candidate.path, "has no copy in it, so there is nothing to check"))
                continue
            # Only the copy is sent, and its places are remembered for the report.
            item["text"] = extracted.text
            extractions[candidate.path] = extracted
        files.append(item)

    if not files:
        out.write(mask(output.text([], warnings, found.skipped, "pass", "No copy files to check.")))
        return 0

    server = args.server or env.get("BRANDLINT_SERVER") or config.server
    if not token:
        err.write("brandlint: set BRANDLINT_TOKEN (a service token from CI settings in BrandLint).\n")
        return 2
    if not server:
        err.write("brandlint: no server. Pass --server, set BRANDLINT_SERVER, or add 'server' to the config.\n")
        return 2

    repo = args.repo or env.get("GITHUB_REPOSITORY") or root.name
    sha = args.sha or env.get("GITHUB_SHA") or _head(root)
    pr = args.pr if args.pr is not None else _pr_from(env)
    client = Client(server, token, timeout=30.0, transport=transport)

    statuses: list[dict[str, Any]] = []
    errors: list[str] = []
    for batch in _batches(files):
        body: dict[str, Any] = {"repo": repo, "pr": pr, "sha": sha, "files": batch}
        if args.base_sha:
            body["base_sha"] = args.base_sha
        try:
            created = client.submit(body)
            status = client.wait(created["id"], args.timeout, sleep=sleep, first=created)
        except ServerError as error:
            errors.append(str(error))
            continue
        statuses.append(status)
        if status["state"] == "error":
            errors.append((status.get("reasons") or ["The run errored."])[0])

    failed = any(s.get("result") == "fail" for s in statuses)
    if failed:
        result, code = "fail", 1
    elif errors:
        result, code = "error", 3
        for message in errors:
            warnings.append(message)
        if args.on_error in ("pass", "warn"):
            warnings.append("BrandLint could not check, and --on-error lets the run through.")
            code = 0
    else:
        result, code = "pass", 0

    output.place_findings(statuses, extractions)
    if args.format == "json":
        text = output.as_json(statuses, warnings, found.skipped, result, code)
    elif args.format == "github":
        text = output.github(statuses, warnings, found.skipped, result)
    elif args.format == "sarif":
        text = output.sarif(statuses, found.skipped)
    else:
        text = output.text(statuses, warnings, found.skipped, result)
    out.write(mask(text))
    return code


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    sleep: Callable[[float], None] = time.sleep,
    transport: Any = None,
) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as stop:  # argparse exits 2 on a usage error, 0 for --help
        return int(stop.code or 0)
    return run_check(args, environ if environ is not None else os.environ, out, err, sleep, transport)


if __name__ == "__main__":
    sys.exit(main())
