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
                where = file["path"] + (":%s" % found["line"] if found.get("line") else "")
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
