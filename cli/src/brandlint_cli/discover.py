"""Finding the files to send: only what the config matches, never outside the repo."""

from __future__ import annotations

import base64
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brandlint_cli.config import ChannelRule, Config

MAX_FILE_BYTES = 5 * 1024 * 1024
BINARY = {".docx", ".pdf", ".png", ".jpg", ".jpeg"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox"}


class UsageError(Exception):
    """The command was asked to do something it won't."""


@dataclass
class Candidate:
    path: str  # relative to the repo root, with forward slashes
    absolute: Path
    rule: ChannelRule


@dataclass
class Discovery:
    files: list[Candidate] = field(default_factory=list)
    # (path, why): shown to the person, so a file that wasn't checked is never a silent pass.
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _walk(start: Path) -> Iterable[Path]:
    for folder, dirs, files in os.walk(start, followlinks=False):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(folder, d))
        )
        for name in sorted(files):
            yield Path(folder) / name


def discover(
    root: Path,
    config: Config,
    paths: list[str] | None = None,
    only: set[str] | None = None,
    max_bytes: int = MAX_FILE_BYTES,
) -> Discovery:
    root = root.resolve()
    found = Discovery()
    chosen: list[Path] = []
    if paths:
        for given in paths:
            target = Path(given) if os.path.isabs(given) else Path.cwd() / given
            if not _inside(root, Path(os.path.abspath(target))) and not os.path.isabs(given):
                # Relative to the repo, as pre-commit hands over names, when --root points elsewhere.
                target = root / given
            if not _inside(root, Path(os.path.abspath(target))):
                raise UsageError(f"{given!r} is outside the repo at {root}, so it is not sent.")
            if target.is_dir() and not target.is_symlink():
                chosen.extend(_walk(target))
            else:
                chosen.append(target)
    elif only is not None:
        chosen = [root / rel for rel in sorted(only)]
    else:
        chosen = list(_walk(root))

    seen: set[str] = set()
    for item in chosen:
        absolute = Path(os.path.abspath(item))
        if not _inside(root, absolute):
            raise UsageError(f"{item} is outside the repo at {root}, so it is not sent.")
        rel = absolute.relative_to(root).as_posix()
        if rel in seen or (only is not None and paths and rel not in only):
            continue
        seen.add(rel)
        if config.ignored(rel):
            continue
        rule = config.rule_for(rel)
        if rule is None:
            continue  # not copy: no rule says so
        if os.path.islink(absolute):
            real = Path(os.path.realpath(absolute))
            if not _inside(root, real):
                found.skipped.append((rel, "a symlink that points outside the repo"))
                continue
        if not absolute.is_file():
            continue
        if absolute.stat().st_size > max_bytes:
            found.skipped.append((rel, f"larger than {max_bytes} bytes, so it was not checked"))
            continue
        found.files.append(Candidate(rel, absolute, rule))
    return found


def payload(candidate: Candidate) -> tuple[dict[str, Any] | None, str | None]:
    """The file as the API takes it, or (None, why) if it can't be sent."""
    data = candidate.absolute.read_bytes()
    base = {
        "path": candidate.path,
        "channel": candidate.rule.channel,
        "data_class": candidate.rule.data_class,
    }
    if candidate.absolute.suffix.lower() in BINARY:
        return {**base, "file_b64": base64.b64encode(data).decode("ascii")}, None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "is not UTF-8 text"
    if not text.strip():
        return None, "is empty"
    return {**base, "text": text}, None
