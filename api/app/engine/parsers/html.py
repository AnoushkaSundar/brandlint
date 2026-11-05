"""HTML parser (BeautifulSoup). Produces heading/paragraph/image blocks and, for
the hidden-content checks, preserves: inline colour/background, font-size,
display/visibility/aria-hidden, HTML comments, and alt/title metadata text.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment

from app.engine.parsers.base import Block, BlockKind, NormalisedDoc, Style

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_TEXT_TAGS = {"p", "li", "blockquote", "figcaption", "td", "th"}
_PT_PER_PX = 0.75  # approximate px -> pt


def _parse_style_attr(style: str | None) -> dict:
    out: dict[str, str] = {}
    if not style:
        return out
    for decl in style.split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip().lower()] = v.strip().lower()
    return out


def _font_pt(decls: dict) -> float | None:
    size = decls.get("font-size")
    if not size:
        return None
    m = re.match(r"([0-9.]+)\s*(px|pt)?", size)
    if not m:
        return None
    value = float(m.group(1))
    return value * _PT_PER_PX if m.group(2) == "px" else value


def _is_hidden(decls: dict, tag) -> bool:
    if decls.get("display") == "none" or decls.get("visibility") == "hidden":
        return True
    return tag.get("aria-hidden") == "true" or tag.has_attr("hidden")


def _style_for(tag) -> Style:
    decls = _parse_style_attr(tag.get("style"))
    return Style(
        color=decls.get("color"),
        background=decls.get("background-color") or decls.get("background"),
        font_pt=_font_pt(decls),
        hidden=_is_hidden(decls, tag),
    )


def parse_html(data: str) -> NormalisedDoc:
    soup = BeautifulSoup(data, "html.parser")
    doc = NormalisedDoc(fmt="html")
    if soup.title and soup.title.string:
        doc.meta["title"] = soup.title.string.strip()

    ordinal = 0
    seen: set[int] = set()
    for tag in soup.find_all(_HEADING_TAGS | _TEXT_TAGS | {"img"}):
        # Skip nested matches already consumed by an ancestor block.
        if any(id(a) in seen for a in tag.parents):
            continue
        seen.add(id(tag))

        if tag.name == "img":
            alt = (tag.get("alt") or "").strip()
            doc.blocks.append(
                Block(
                    kind=BlockKind.image,
                    text=alt,
                    ordinal=ordinal,
                    image_ref=tag.get("src"),
                    style=Style(from_metadata=bool(alt)),
                )
            )
            ordinal += 1
            continue

        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        is_heading = tag.name in _HEADING_TAGS
        doc.blocks.append(
            Block(
                kind=BlockKind.heading if is_heading else BlockKind.paragraph,
                text=text,
                ordinal=ordinal,
                level=int(tag.name[1]) if is_heading else None,
                style=_style_for(tag),
            )
        )
        ordinal += 1

    # HTML comments — a common place to hide instructions.
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        text = str(comment).strip()
        if text:
            doc.blocks.append(
                Block(
                    kind=BlockKind.paragraph,
                    text=text,
                    ordinal=ordinal,
                    style=Style(from_comment=True),
                )
            )
            ordinal += 1

    return doc
