"""The repo's `.brandlint.yml`: which files hold copy, and how to read them.

No file is scanned unless a rule here matches it. Policy hints are informational: the
server decides what fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern
from typing import Any

import yaml

from brandlint_cli.globs import glob_to_regex

CHANNELS = ("blog", "linkedin", "email", "ad", "banner", "document")
DATA_CLASSES = ("public", "internal", "confidential", "restricted")
EXTRACTORS = ("plain", "json-i18n", "yaml-i18n", "po", "properties", "html-text")
CONFIG_NAME = ".brandlint.yml"


class ConfigError(Exception):
    """The config can't be used. The message says what to change."""


@dataclass
class ChannelRule:
    glob: str
    channel: str
    extract: str = "plain"
    data_class: str = "public"
    regex: Pattern[str] | None = field(default=None, repr=False)

    def matches(self, path: str) -> bool:
        return bool(self.regex and self.regex.match(path))


@dataclass
class Config:
    server: str | None = None
    channels: list[ChannelRule] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)

    def rule_for(self, path: str) -> ChannelRule | None:
        for rule in self.channels:
            if rule.matches(path):
                return rule
        return None

    def ignored(self, path: str) -> bool:
        return any(glob_to_regex(pattern).match(path) for pattern in self.ignore)


def _choice(value: Any, allowed: tuple, where: str) -> str:
    if value not in allowed:
        raise ConfigError(f"{where} must be one of {', '.join(allowed)} (got {value!r}).")
    return str(value)


def parse(text: str, where: str = CONFIG_NAME) -> Config:
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as error:
        raise ConfigError(f"{where} isn't valid YAML: {error}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping at the top level.")
    unknown = set(raw) - {"server", "channels", "ignore", "policy"}
    if unknown:
        raise ConfigError(f"{where} has unknown keys: {', '.join(sorted(unknown))}.")
    channels = raw.get("channels")
    if not isinstance(channels, list) or not channels:
        raise ConfigError(f"{where} needs a 'channels' list saying which files hold copy.")
    rules = []
    for index, item in enumerate(channels, start=1):
        label = f"channels[{index}]"
        if not isinstance(item, dict) or "glob" not in item or "channel" not in item:
            raise ConfigError(f"{label} needs a 'glob' and a 'channel'.")
        extra = set(item) - {"glob", "channel", "extract", "data_class"}
        if extra:
            raise ConfigError(f"{label} has unknown keys: {', '.join(sorted(extra))}.")
        glob = str(item["glob"])
        if glob.startswith("/") or ".." in glob.split("/"):
            raise ConfigError(f"{label}.glob must be relative to the repo and can't contain '..'.")
        rules.append(
            ChannelRule(
                glob=glob,
                channel=_choice(item["channel"], CHANNELS, f"{label}.channel"),
                extract=_choice(item.get("extract", "plain"), EXTRACTORS, f"{label}.extract"),
                data_class=_choice(item.get("data_class", "public"), DATA_CLASSES, f"{label}.data_class"),
                regex=glob_to_regex(glob),
            )
        )
    ignore = raw.get("ignore") or []
    if not isinstance(ignore, list) or not all(isinstance(p, str) for p in ignore):
        raise ConfigError(f"{where}: 'ignore' must be a list of globs.")
    server = raw.get("server")
    if server is not None and not isinstance(server, str):
        raise ConfigError(f"{where}: 'server' must be a URL.")
    policy = raw.get("policy") or {}
    if not isinstance(policy, dict):
        raise ConfigError(f"{where}: 'policy' must be a mapping.")
    return Config(server=server, channels=rules, ignore=list(ignore), policy=policy)


def load(path: Path) -> Config:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            f"No {path.name} found at {path}. Add one saying which files hold copy "
            "(see the BrandLint CI guide)."
        ) from None
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"Couldn't read {path}: {error}") from None
    return parse(text, path.name)
