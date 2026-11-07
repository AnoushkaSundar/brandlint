"""Accessibility checks: tier 0, pure code, no model. Each cites a WCAG criterion."""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from bs4 import BeautifulSoup

from app.checks.accessibility.contrast import (
    RGB,
    contrast_ratio,
    nearest_passing,
    parse_colour,
    required_ratio,
    to_hex,
)
from app.contracts import CheckType, Finding, Severity, TraceStep
from app.engine.checks.context import CheckContext, make_finding
from app.engine.chunking import ParsedChunk

WCAG_TEXT = {
    "WCAG-1.1.1": (
        "All non-text content that is presented to the user has a text alternative "
        "that serves the equivalent purpose."
    ),
    "WCAG-1.3.1": (
        "Information, structure and relationships conveyed through presentation can "
        "be programmatically determined or are available in text."
    ),
    "WCAG-1.4.3": (
        "The visual presentation of text and images of text has a contrast ratio of "
        "at least 4.5:1, except large text, which needs at least 3:1."
    ),
    "WCAG-2.4.4": (
        "The purpose of each link can be determined from the link text alone or from "
        "the link text together with its context."
    ),
}
WCAG_RULE_IDS = frozenset(WCAG_TEXT)

BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)
LARGE_TEXT_PX = 24
MIN_OCR_CONFIDENCE = 40
TEXT_PERCENTILE = 80
OCR_SCALE = 2
MASK_DISTANCE = 20

_FILE_NAME = re.compile(r"\.(png|jpe?g|gif|svg|webp|tiff?|bmp)$", re.IGNORECASE)
_MEANINGLESS_ALT = {
    "image", "img", "picture", "pic", "photo", "graphic", "icon", "screenshot",
    "untitled", "placeholder",
}
_VAGUE_LINKS = {
    "click here", "here", "read more", "learn more", "more", "this", "this link",
    "link", "details", "go",
}
_BARE_URL = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
_HEADING_STYLE = re.compile(r"^Heading (\d)$")

OcrFn = Callable[[Any], list[dict]]


@dataclass(frozen=True)
class Heading:
    level: int
    text: str


def _finding(
    ctx: CheckContext,
    rule_id: str,
    severity: Severity,
    explanation: str,
    anchor: str,
    spans: list[dict] | None = None,
) -> Finding:
    return make_finding(
        ctx,
        check=CheckType.accessibility,
        severity=severity,
        cited_text=WCAG_TEXT[rule_id],
        explanation=explanation,
        anchor=f"{rule_id}:{anchor}",
        spans=spans,
        unit_type="chunk" if spans else "document",
        rule_id=rule_id,
        sources=[rule_id],
        tool="accessibility",
    )


def _span_of(
    text: str, chunks: Sequence[ParsedChunk], taken: set | None = None
) -> list[dict]:
    """The first occurrence not already used, so repeated text gets its own span."""
    for chunk in chunks:
        start = chunk.text.find(text)
        while start >= 0:
            key = (chunk.id, start)
            if taken is None or key not in taken:
                if taken is not None:
                    taken.add(key)
                return [{"chunk_id": chunk.id, "start": start, "end": start + len(text)}]
            start = chunk.text.find(text, start + 1)
    return []


def _contrast_finding(
    ctx: CheckContext,
    foreground: RGB,
    background: RGB,
    needed: float,
    palette: Sequence[RGB],
    anchor: str,
    spans: list[dict] | None,
    label: str,
) -> Finding | None:
    ratio = contrast_ratio(foreground, background)
    if ratio >= needed:
        return None
    pair = f"{to_hex(foreground)} on {to_hex(background)}"
    suggestion = nearest_passing(foreground, background, palette, needed)
    advice = f" {to_hex(suggestion)} from the palette passes." if suggestion else ""
    finding = _finding(
        ctx,
        "WCAG-1.4.3",
        Severity.medium,
        f"{label} has a contrast ratio of {ratio:.1f}:1 ({pair}). "
        f"It needs at least {needed:g}:1.{advice}",
        anchor,
        spans,
    )
    # The review screen draws the preview from this step.
    finding.trace.steps.append(
        TraceStep(
            tool="contrast_preview",
            input_summary=pair,
            output_summary=(
                f"{ratio:.1f}:1, needs {needed:g}:1"
                + (f", try {to_hex(suggestion)}" if suggestion else "")
            ),
        )
    )
    return finding


def _is_visible(style: dict) -> bool:
    return not any(
        style.get(flag) for flag in ("hidden", "from_comment", "from_metadata", "from_ocr")
    )


def check_chunk_contrast(
    chunks: Sequence[ParsedChunk], ctx: CheckContext, palette: Sequence[RGB] = ()
) -> list[Finding]:
    """Contrast for text whose colours the parser recorded.

    A colour nobody set falls back to black on white, the browser's default. Identical
    colours are hidden text, which the hidden-content check reports instead.
    """
    findings = []
    for chunk in chunks:
        style = chunk.style or {}
        if not chunk.text.strip() or not _is_visible(style):
            continue
        raw_fg, raw_bg = style.get("color"), style.get("background")
        if not raw_fg and not raw_bg:
            continue
        # Unset means the browser default. Set but unreadable means we don't know,
        # and an invented pair would give a false finding.
        foreground = parse_colour(raw_fg) if raw_fg else BLACK
        background = parse_colour(raw_bg) if raw_bg else WHITE
        if foreground is None or background is None:
            continue
        if foreground == background:
            continue
        found = _contrast_finding(
            ctx,
            foreground,
            background,
            required_ratio(style.get("font_pt")),
            palette,
            chunk.id,
            [{"chunk_id": chunk.id, "start": 0, "end": len(chunk.text)}],
            "This text",
        )
        if found:
            findings.append(found)
    return findings


def _alt_problem(alt: str | None) -> str | None:
    if alt is None:
        return "has no alt text"
    text = alt.strip()
    if not text:
        return "has empty alt text"
    if _FILE_NAME.search(text):
        return f'uses a file name as alt text ("{text}")'
    if text.lower() in _MEANINGLESS_ALT or text.isdigit():
        return f'has meaningless alt text ("{text}")'
    return None


def _alt_findings(
    ctx: CheckContext, images: Sequence[tuple[str, str | None]]
) -> list[Finding]:
    findings = []
    for index, (name, alt) in enumerate(images):
        problem = _alt_problem(alt)
        if problem:
            findings.append(
                _finding(
                    ctx,
                    "WCAG-1.1.1",
                    Severity.medium,
                    f"Image {name} {problem}.",
                    f"image-{index}",
                )
            )
    return findings


def _heading_findings(
    ctx: CheckContext, headings: Sequence[Heading], chunks: Sequence[ParsedChunk]
) -> list[Finding]:
    findings = []
    taken: set = set()
    firsts = [heading for heading in headings if heading.level == 1]
    for extra in firsts[1:]:
        findings.append(
            _finding(
                ctx,
                "WCAG-1.3.1",
                Severity.low,
                f'There is more than one top-level heading: "{extra.text}".',
                f"h1:{extra.text}",
                _span_of(extra.text, chunks, taken),
            )
        )
    for previous, current in itertools.pairwise(headings):
        if current.level > previous.level + 1:
            findings.append(
                _finding(
                    ctx,
                    "WCAG-1.3.1",
                    Severity.low,
                    f'The heading "{current.text}" skips from level '
                    f"{previous.level} to level {current.level}.",
                    f"skip:{current.text}",
                    _span_of(current.text, chunks, taken),
                )
            )
    return findings


def _link_findings(
    ctx: CheckContext, links: Sequence[str], chunks: Sequence[ParsedChunk]
) -> list[Finding]:
    findings = []
    taken: set = set()
    for index, text in enumerate(links):
        label = " ".join(text.split())
        if label.lower().strip(".!?:") in _VAGUE_LINKS:
            problem = "doesn't say where the link goes"
        elif _BARE_URL.match(label):
            problem = "is a bare web address"
        else:
            continue
        findings.append(
            _finding(
                ctx,
                "WCAG-2.4.4",
                Severity.low,
                f'The link text "{label}" {problem}.',
                f"link-{index}",
                _span_of(label, chunks, taken),
            )
        )
    return findings


def check_html(
    html: str, chunks: Sequence[ParsedChunk], ctx: CheckContext
) -> list[Finding]:
    soup = BeautifulSoup(html, "html.parser")
    images = [
        (tag.get("src") or "without a source", tag.get("alt"))
        for tag in soup.find_all("img")
        if tag.get("role") != "presentation"
    ]
    headings = [
        Heading(int(tag.name[1]), tag.get_text(" ", strip=True))
        for tag in soup.find_all(re.compile(r"^h[1-6]$"))
    ]
    links = [tag.get_text(" ", strip=True) for tag in soup.find_all("a") if tag.get("href")]
    return [
        *_alt_findings(ctx, images),
        *_heading_findings(ctx, headings, chunks),
        *_link_findings(ctx, links, chunks),
    ]


def check_docx(
    data: bytes, chunks: Sequence[ParsedChunk], ctx: CheckContext
) -> list[Finding]:
    from docx import Document  # lazy, as in the parsers
    from docx.oxml.ns import qn

    document = Document(BytesIO(data))
    body = document.element.body

    images = []
    for shape in body.iter(qn("wp:docPr")):
        name = shape.get("name") or "in the document"
        images.append((name, shape.get("descr")))

    headings = []
    for paragraph in document.paragraphs:
        style = paragraph.style.name if paragraph.style else ""
        match = _HEADING_STYLE.match(style or "")
        level = 0 if style == "Title" else int(match.group(1)) if match else None
        if level is not None and paragraph.text.strip():
            headings.append(Heading(level, paragraph.text.strip()))

    links = [
        "".join(node.text or "" for node in link.iter(qn("w:t")))
        for link in body.iter(qn("w:hyperlink"))
    ]
    return [
        *_alt_findings(ctx, images),
        *_heading_findings(ctx, headings, chunks),
        *_link_findings(ctx, links, chunks),
    ]


def _standout(image: Any) -> Any:
    """A black-on-white mask of everything that differs from the background.

    Faint text is what this check looks for and also what OCR can't read, so it gets a
    copy where any text is solid, however close its colour is to the background.
    """
    import cv2
    import numpy as np
    from PIL import Image

    pixels = np.asarray(image).astype(np.float32)
    colours, counts = np.unique(
        pixels.reshape(-1, 3).astype(np.uint8), axis=0, return_counts=True
    )
    background = colours[int(np.argmax(counts))].astype(np.float32)
    distance = np.linalg.norm(pixels - background, axis=2)
    mask = np.where(distance > MASK_DISTANCE, 0, 255).astype(np.uint8)
    scaled = cv2.resize(
        mask, None, fx=OCR_SCALE, fy=OCR_SCALE, interpolation=cv2.INTER_CUBIC
    )
    return Image.fromarray(scaled)


def _read_lines(image: Any, scale: int = 1) -> list[dict]:
    import pytesseract  # lazy: needs the tesseract binary
    from pytesseract import Output

    data = pytesseract.image_to_data(image, output_type=Output.DICT)
    lines: dict[tuple[int, int, int], dict] = {}
    for index, word in enumerate(data["text"]):
        if not word.strip() or float(data["conf"][index]) < MIN_OCR_CONFIDENCE:
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        left, top = data["left"][index] // scale, data["top"][index] // scale
        right = left + data["width"][index] // scale
        bottom = top + data["height"][index] // scale
        line = lines.setdefault(
            key, {"left": left, "top": top, "right": right, "bottom": bottom, "words": []}
        )
        line["left"] = min(line["left"], left)
        line["top"] = min(line["top"], top)
        line["right"] = max(line["right"], right)
        line["bottom"] = max(line["bottom"], bottom)
        line["words"].append(word)
    return [{**line, "text": " ".join(line["words"])} for line in lines.values()]


def _overlaps(first: dict, second: dict) -> bool:
    return (
        first["left"] < second["right"]
        and second["left"] < first["right"]
        and first["top"] < second["bottom"]
        and second["top"] < first["bottom"]
    )


def _ocr_lines(image: Any) -> list[dict]:
    """Text lines as boxes in image coordinates, faint text included."""
    lines = _read_lines(image)
    for line in _read_lines(_standout(image), OCR_SCALE):
        if not any(_overlaps(line, known) for known in lines):
            lines.append(line)
    return lines


def _box_colours(pixels: Any) -> tuple[RGB, RGB]:
    """Text and background colours of a box. The background covers more of it."""
    import cv2
    import numpy as np

    samples = pixels.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    cv2.setRNGSeed(0)
    _, labels, centres = cv2.kmeans(samples, 2, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=2)
    background_label = int(np.argmax(counts))
    background = centres[background_label]
    text_pixels = samples[labels.flatten() != background_label]
    if len(text_pixels) == 0:
        foreground = centres[int(np.argmin(counts))]
    else:
        # Edge pixels blend into the background, so only the most distinct count.
        distance = np.linalg.norm(text_pixels - background, axis=1)
        strongest = text_pixels[distance >= np.percentile(distance, TEXT_PERCENTILE)]
        foreground = np.median(strongest, axis=0)
    as_rgb = lambda centre: tuple(round(float(value)) for value in centre)
    return as_rgb(foreground), as_rgb(background)


def check_image_contrast(
    data: bytes,
    chunks: Sequence[ParsedChunk],
    ctx: CheckContext,
    palette: Sequence[RGB] = (),
    *,
    ocr: OcrFn = _ocr_lines,
) -> list[Finding]:
    """Contrast of the text in an image, from OCR boxes against sampled colours."""
    import numpy as np
    from PIL import Image

    image = Image.open(BytesIO(data)).convert("RGB")
    pixels = np.asarray(image)
    findings = []
    for index, line in enumerate(ocr(image)):
        box = pixels[line["top"] : line["bottom"], line["left"] : line["right"]]
        if box.size == 0:
            continue
        foreground, background = _box_colours(box)
        height = line["bottom"] - line["top"]
        needed = required_ratio(18.0 if height >= LARGE_TEXT_PX else None)
        found = _contrast_finding(
            ctx,
            foreground,
            background,
            needed,
            palette,
            f"ocr-{index}",
            _span_of(line["text"], chunks),
            f'The text "{line["text"]}"',
        )
        if found:
            findings.append(found)
    return findings


def check_accessibility(
    data: bytes | str,
    fmt: str,
    chunks: Sequence[ParsedChunk],
    ctx: CheckContext,
    palette: Sequence[RGB] = (),
) -> list[Finding]:
    """Every accessibility check for this format. `fmt` is the tier-0 format name."""
    findings = check_chunk_contrast(chunks, ctx, palette)
    if fmt == "html":
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
        findings += check_html(text, chunks, ctx)
    elif fmt == "docx" and isinstance(data, bytes):
        findings += check_docx(data, chunks, ctx)
    elif fmt == "image" and isinstance(data, bytes):
        findings += check_image_contrast(data, chunks, ctx, palette)
    return findings
