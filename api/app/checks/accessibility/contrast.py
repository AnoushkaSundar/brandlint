"""WCAG contrast: pure arithmetic, so the same colours always give the same answer."""

import re
from collections.abc import Iterable

RGB = tuple[int, int, int]

NORMAL_RATIO = 4.5
LARGE_RATIO = 3.0
LARGE_PT = 18.0
LARGE_BOLD_PT = 14.0

_NAMED = {"white": "#ffffff", "black": "#000000"}
_RGB_CALL = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def parse_colour(value: str | None) -> RGB | None:
    """Reads #rgb, #rrggbb, rgb() and the two names that matter. None if unknown."""
    if not value:
        return None
    text = _NAMED.get(value.strip().lower(), value.strip().lower())
    call = _RGB_CALL.match(text)
    if call:
        red, green, blue = (min(int(part), 255) for part in call.groups())
        return red, green, blue
    digits = text.removeprefix("#")
    if len(digits) == 3:
        digits = "".join(part * 2 for part in digits)
    if len(digits) != 6 or not text.startswith("#"):
        return None
    try:
        return int(digits[:2], 16), int(digits[2:4], 16), int(digits[4:], 16)
    except ValueError:
        return None


def to_hex(colour: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*colour)


def _linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(colour: RGB) -> float:
    red, green, blue = (_linear(channel) for channel in colour)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: RGB, second: RGB) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def required_ratio(font_pt: float | None, *, bold: bool = False) -> float:
    if font_pt is None:
        return NORMAL_RATIO
    large = font_pt >= LARGE_PT or (bold and font_pt >= LARGE_BOLD_PT)
    return LARGE_RATIO if large else NORMAL_RATIO


def nearest_passing(
    foreground: RGB, background: RGB, palette: Iterable[RGB], needed: float
) -> RGB | None:
    """The palette colour closest to the text colour that passes on this background."""
    passing = [
        colour for colour in palette if contrast_ratio(colour, background) >= needed
    ]
    if not passing:
        return None
    return min(
        passing,
        key=lambda colour: sum((a - b) ** 2 for a, b in zip(colour, foreground, strict=True)),
    )
