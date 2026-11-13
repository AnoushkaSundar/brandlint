"""Path globs: `**` crosses folders, `*` and `?` stay inside one."""

from __future__ import annotations

import re
from re import Pattern


def glob_to_regex(glob: str) -> Pattern[str]:
    out = ""
    i = 0
    while i < len(glob):
        char = glob[i]
        if glob.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if glob.startswith("**", i):
            out += ".*"
            i += 2
            continue
        if char == "*":
            out += "[^/]*"
        elif char == "?":
            out += "[^/]"
        else:
            out += re.escape(char)
        i += 1
    return re.compile("^" + out + "$")
