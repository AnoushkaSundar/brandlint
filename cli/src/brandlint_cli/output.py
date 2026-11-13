"""What the tool prints. Formats are text and json (here), and github and sarif (with the
line mapping). Nothing here quotes a draft beyond the server's short span, and every line
goes through the token mask before it is written."""

from __future__ import annotations

import json
from typing import Any

SHORT = 80


def _short(text: str, size: int = SHORT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= size else text[: size - 1] + "…"


def place_findings(statuses: list[dict[str, Any]], extractions: dict[str, Any]) -> None:
    """Adds `location` (path, line, column, key) to each finding: where it is in the file,
    worked out from the line the server gave in the text that was sent."""
    for status in statuses:
        for file in status.get("files", []):
            extracted = extractions.get(file["path"])
            for found in file.get("findings", []):
                line = found.get("line")
                if line is None and extracted is not None and found.get("span"):
                    index = extracted.text.find(found["span"][:60])
                    line = extracted.text.count("\n", 0, index) + 1 if index >= 0 else None
                place = extracted.locate(line) if extracted is not None else None
                found["location"] = {
                    "path": file["path"],
                    "line": place.line if place else line,
                    "column": place.column if place else None,
                    "key": place.key if place else None,
                }


def _where(found: dict[str, Any], path: str) -> str:
    place = found.get("location") or {}
    line = place.get("line") or found.get("line")
    where = f"{path}:{line}" if line else path
    return f"{where} [{place['key']}]" if place.get("key") else where


def _escape(value: str, *, prop: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if prop else value


def github(statuses, warnings, skipped, result) -> str:
    """Workflow commands: GitHub shows each as an annotation on the changed line."""
    lines = []
    for status in statuses:
        for file in status.get("files", []):
            for found in file.get("findings", []):
                place = found.get("location") or {}
                level = "error" if found.get("blocking") else "warning"
                fields = [f"file={_escape(file['path'], prop=True)}"]
                if place.get("line"):
                    fields.append(f"line={place['line']}")
                if place.get("column"):
                    fields.append(f"col={place['column']}")
                fields.append("title=BrandLint")
                key = f" [{place['key']}]" if place.get("key") else ""
                rule = found.get("rule_id") or "no rule"
                message = f"{found['title']}{key} ({rule}, {found['severity']}) {found['url']}"
                lines.append(f"::{level} {','.join(fields)}::{_escape(message)}")
    for path, why in skipped:
        note = _escape("Not checked: " + why)
        lines.append(f"::warning file={_escape(path, prop=True)},title=BrandLint::{note}")
    for warning in warnings:
        lines.append(f"::warning title=BrandLint::{_escape(warning)}")
    lines.append(f"BrandLint {verdict_word(result)}.")
    for status in statuses:
        lines.append(f"Run: {status['url']}")
    return "\n".join(lines) + "\n"


def sarif(statuses, skipped) -> str:
    """SARIF 2.1.0, for GitHub code scanning. Blocking findings are errors."""
    rules: dict[str, dict[str, Any]] = {}
    results = []
    for status in statuses:
        for file in status.get("files", []):
            for found in file.get("findings", []):
                rule_id = found.get("rule_id") or "no-rule"
                rules.setdefault(
                    rule_id,
                    {"id": rule_id, "name": rule_id, "shortDescription": {"text": found["title"]}},
                )
                place = found.get("location") or {}
                region = {"startLine": place.get("line") or 1}
                if place.get("column"):
                    region["startColumn"] = place["column"]
                results.append(
                    {
                        "ruleId": rule_id,
                        "level": "error" if found.get("blocking") else "note",
                        "message": {"text": f"{found['title']} ({found['severity']}). {found['url']}"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": file["path"]},
                                    "region": region,
                                }
                            }
                        ],
                        "properties": {
                            "severity": found["severity"],
                            "status": found["status"],
                            "key": place.get("key"),
                            "url": found["url"],
                        },
                    }
                )
    notifications = [
        {"level": "warning", "message": {"text": f"{path} was not checked: {why}"}}
        for path, why in skipped
    ]
    document = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "BrandLint", "rules": list(rules.values())}},
                "results": results,
                "invocations": [
                    {"executionSuccessful": True, "toolExecutionNotifications": notifications}
                ],
            }
        ],
    }
    return json.dumps(document, indent=2) + "\n"


def verdict_word(result: str) -> str:
    return {"pass": "PASSED", "fail": "FAILED", "error": "COULD NOT CHECK"}[result]


def text(
    statuses: list[dict[str, Any]],
    warnings: list[str],
    skipped: list[tuple[str, str]],
    result: str,
    note: str = "",
) -> str:
    lines: list[str] = []
    for status in statuses:
        for file in status.get("files", []):
            for found in file.get("findings", []):
                where = _where(found, file["path"])
                mark = "BLOCKS " if found.get("blocking") else "       "
                rule = found.get("rule_id") or "no rule"
                lines.append(
                    f"{mark}{where}  [{found['severity']}] {found['title']} ({rule}) {found['url']}"
                )
                if found.get("span"):
                    lines.append(f"         {_short(found['span'])}")
    for path, why in skipped:
        lines.append(f"SKIPPED {path}: {why}")
    for warning in warnings:
        lines.append(f"WARNING {warning}")
    if note:
        lines.append(note)
    for status in statuses:
        for reason in status.get("reasons", [])[:1]:
            lines.append(reason)
    lines.append(f"BrandLint {verdict_word(result)}.")
    for status in statuses:
        lines.append(f"Run: {status['url']}")
    return "\n".join(lines) + "\n"


def as_json(
    statuses: list[dict[str, Any]],
    warnings: list[str],
    skipped: list[tuple[str, str]],
    result: str,
    exit_code: int,
) -> str:
    return (
        json.dumps(
            {
                "result": result,
                "exit_code": exit_code,
                "runs": statuses,
                "warnings": warnings,
                "skipped": [{"path": p, "reason": why} for p, why in skipped],
            },
            indent=2,
        )
        + "\n"
    )
