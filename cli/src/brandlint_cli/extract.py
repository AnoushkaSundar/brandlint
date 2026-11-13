"""Finding the copy inside files that also hold code, and remembering where each piece was.

An extractor reads a file and returns its pieces of copy, each with the key it lives under
and its line and column in the file. The pieces are joined into one text to send, and
`Extracted.locate` turns a line in that text back into a place in the file.

Placeholders ({name}, {{name}}, %s, ICU groups) are replaced by a neutral word before
sending, so they are not read as product terms. Strings that are only URLs, numbers or
placeholders are not copy, and are not sent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import yaml

PLACEHOLDER = "[placeholder]"
PRINTF = re.compile(r"%(?:\d+\$)?(?:\([^)]+\))?[-+ 0#]*\d*(?:\.\d+)?[sdifgeEcrxXo]")
URL = re.compile(r"^\s*(?:https?://|mailto:|www\.)\S+\s*$")


def mask_placeholders(text: str) -> str:
    """Replaces each placeholder with a neutral word. Brace groups may nest (ICU messages)."""
    out: list[str] = []
    depth = 0
    for char in text:
        if char == "{":
            if depth == 0:
                out.append(PLACEHOLDER)
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
        elif depth == 0:
            out.append(char)
    return PRINTF.sub(PLACEHOLDER, "".join(out))


def is_copy(text: str) -> bool:
    """Whether a string is words for a reader, after its placeholders are masked."""
    if URL.match(text):
        return False
    letters = re.sub(re.escape(PLACEHOLDER), " ", mask_placeholders(text))
    return bool(re.search(r"[^\W\d_]{2,}", letters))


@dataclass
class Segment:
    text: str
    line: int  # 1-based line in the file
    column: int  # 1-based column in the file
    key: str | None = None
    # Where it sits in the text that is sent (1-based lines), set when the text is built.
    sent_first: int = 1
    sent_last: int = 1


@dataclass
class Location:
    line: int
    column: int
    key: str | None


@dataclass
class Extracted:
    segments: list[Segment] = field(default_factory=list)
    text: str = ""

    def build(self) -> Extracted:
        parts, line = [], 1
        for segment in self.segments:
            height = segment.text.count("\n") + 1
            segment.sent_first, segment.sent_last = line, line + height - 1
            parts.append(segment.text)
            line += height + 1  # a blank line between pieces
        self.text = "\n\n".join(parts)
        return self

    def locate(self, sent_line: int | None) -> Location | None:
        """The place in the file for a line of the text that was sent."""
        if sent_line is None:
            return None
        for segment in self.segments:
            if segment.sent_first <= sent_line <= segment.sent_last:
                return Location(
                    segment.line + (sent_line - segment.sent_first), segment.column, segment.key
                )
        return None


# --- Readers ------------------------------------------------------------------------------


def plain(source: str) -> Extracted:
    return Extracted([Segment(source, 1, 1)]).build()


def _line_starts(source: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\n", source):
        starts.append(match.end())
    return starts


def _position(starts: list[int], index: int) -> tuple[int, int]:
    low, high = 0, len(starts) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if starts[middle] <= index:
            low = middle
        else:
            high = middle - 1
    return low + 1, index - starts[low] + 1


def json_i18n(source: str) -> Extracted:
    data = json.loads(source)
    starts = _line_starts(source)
    cursor = 0
    found: list[Segment] = []

    def find(value: str, start: int) -> int:
        for literal in (json.dumps(value, ensure_ascii=False), json.dumps(value)):
            index = source.find(literal, start)
            if index >= 0:
                return index
        return -1

    def walk(node: Any, path: str) -> None:
        nonlocal cursor
        if isinstance(node, dict):
            for key, value in node.items():
                at = find(str(key), cursor)
                if at >= 0:
                    cursor = at + len(str(key)) + 2
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for number, value in enumerate(node):
                walk(value, f"{path}[{number}]")
        elif isinstance(node, str):
            at = find(node, cursor)
            if at >= 0:
                cursor = at + 1
            if is_copy(node):
                line, column = _position(starts, at) if at >= 0 else (1, 1)
                found.append(Segment(mask_placeholders(node), line, column + 1, path))

    walk(data, "")
    return Extracted(found).build()


def yaml_i18n(source: str) -> Extracted:
    root = yaml.compose(source)
    found: list[Segment] = []

    def walk(node: Any, path: str) -> None:
        if node is None:
            return
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = str(getattr(key_node, "value", ""))
                walk(value_node, f"{path}.{key}" if path else key)
        elif isinstance(node, yaml.SequenceNode):
            for number, item in enumerate(node.value):
                walk(item, f"{path}[{number}]")
        elif isinstance(node, yaml.ScalarNode) and node.tag == "tag:yaml.org,2002:str":
            if is_copy(node.value):
                found.append(
                    Segment(
                        mask_placeholders(node.value),
                        node.start_mark.line + 1,
                        node.start_mark.column + 1,
                        path,
                    )
                )

    walk(root, "")
    return Extracted(found).build()


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        try:
            return json.loads(raw)
        except ValueError:
            return raw[1:-1]
    return raw


def po(source: str) -> Extracted:
    found: list[Segment] = []
    msgid: list[str] = []
    current: dict[str, Any] | None = None  # the msgstr being read: its lines and where it began

    def finish() -> None:
        nonlocal current
        if current is not None:
            text = "".join(current["parts"])
            key = "".join(msgid)
            if key and is_copy(text):
                found.append(
                    Segment(mask_placeholders(text), current["line"], current["column"], key)
                )
        current = None

    reading = None
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("msgid_plural"):
            reading = None
        elif stripped.startswith("msgid"):
            finish()
            msgid = [_unquote(stripped[5:])]
            reading = "id"
        elif stripped.startswith("msgstr"):
            finish()
            rest = re.sub(r"^msgstr(\[\d+\])?", "", stripped)
            current = {
                "parts": [_unquote(rest)],
                "line": number,
                "column": line.index('"') + 2 if '"' in line else 1,
            }
            reading = "str"
        elif stripped.startswith('"'):
            if reading == "id":
                msgid.append(_unquote(stripped))
            elif reading == "str" and current is not None:
                current["parts"].append(_unquote(stripped))
        elif not stripped or stripped.startswith("#"):
            if not stripped:
                finish()
                reading = None
    finish()
    return Extracted(found).build()


def properties(source: str) -> Extracted:
    found: list[Segment] = []
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        index += 1
        if not stripped or stripped[0] in "#!":
            continue
        first = index
        value_line = stripped
        while value_line.endswith("\\") and not value_line.endswith("\\\\") and index < len(lines):
            value_line = value_line[:-1] + lines[index].strip()
            index += 1
        match = re.match(r"^((?:\\.|[^=:\s\\])+)\s*[=:\s]\s*(.*)$", value_line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        value = (
            re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)
            .replace("\\n", "\n")
            .replace("\\t", "\t")
        )
        if is_copy(value):
            column = raw.index(match.group(2)) + 1 if match.group(2) and match.group(2) in raw else 1
            found.append(Segment(mask_placeholders(value), first, column, key))
    return Extracted(found).build()


class _Visible(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "head", "title"}

    def __init__(self) -> None:
        super().__init__()
        self.depth: list[str] = []
        self.found: list[Segment] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP:
            self.depth.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.depth and self.depth[-1] == tag:
            self.depth.pop()

    def handle_data(self, data: str) -> None:
        if self.depth or not is_copy(data.strip()):
            return
        line, column = self.getpos()
        lead = len(data) - len(data.lstrip())
        text = " ".join(data.split())
        self.found.append(Segment(mask_placeholders(text), line, column + 1 + lead, None))


def html_text(source: str) -> Extracted:
    parser = _Visible()
    parser.feed(source)
    parser.close()
    return Extracted(parser.found).build()


EXTRACTORS = {
    "plain": plain,
    "json-i18n": json_i18n,
    "yaml-i18n": yaml_i18n,
    "po": po,
    "properties": properties,
    "html-text": html_text,
}


class ExtractionError(Exception):
    """The file could not be read the way the config says."""


def extract(kind: str, source: str) -> Extracted:
    try:
        return EXTRACTORS[kind](source)
    except (ValueError, yaml.YAMLError) as error:
        raise ExtractionError(f"is not valid {kind.split('-')[0].upper()}: {error}") from None
