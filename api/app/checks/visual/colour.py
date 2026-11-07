"""Perceptual colour distance. CIEDE2000 is the standard measure of how different two
colours look, so "off palette" means what a person would see.
"""

import math

RGB = tuple[int, int, int]
Lab = tuple[float, float, float]

_WHITE_D65 = (0.95047, 1.0, 1.08883)


def _linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _f(value: float) -> float:
    return value ** (1 / 3) if value > 216 / 24389 else (24389 / 27 * value + 16) / 116


def rgb_to_lab(colour: RGB) -> Lab:
    red, green, blue = (_linear(channel) for channel in colour)
    x = 0.4124564 * red + 0.3575761 * green + 0.1804375 * blue
    y = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue
    z = 0.0193339 * red + 0.1191920 * green + 0.9503041 * blue
    fx, fy, fz = (_f(v / w) for v, w in zip((x, y, z), _WHITE_D65, strict=True))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _hue(a: float, b: float) -> float:
    if a == 0 and b == 0:
        return 0.0
    return math.degrees(math.atan2(b, a)) % 360


def delta_e_2000(first: Lab, second: Lab) -> float:
    """Sharma, Wu and Dalal's formulation, which the test data below comes from."""
    l1, a1, b1 = first
    l2, a2, b2 = second

    c_mean = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(c_mean**7 / (c_mean**7 + 25**7)))
    a1_p, a2_p = (1 + g) * a1, (1 + g) * a2
    c1_p, c2_p = math.hypot(a1_p, b1), math.hypot(a2_p, b2)
    h1_p, h2_p = _hue(a1_p, b1), _hue(a2_p, b2)

    dl = l2 - l1
    dc = c2_p - c1_p
    dh_deg = 0.0
    if c1_p * c2_p != 0:
        dh_deg = h2_p - h1_p
        if dh_deg > 180:
            dh_deg -= 360
        elif dh_deg < -180:
            dh_deg += 360
    dh = 2 * math.sqrt(c1_p * c2_p) * math.sin(math.radians(dh_deg) / 2)

    l_mean = (l1 + l2) / 2
    c_p_mean = (c1_p + c2_p) / 2
    if c1_p * c2_p == 0:
        h_mean = h1_p + h2_p
    elif abs(h1_p - h2_p) <= 180:
        h_mean = (h1_p + h2_p) / 2
    elif h1_p + h2_p < 360:
        h_mean = (h1_p + h2_p + 360) / 2
    else:
        h_mean = (h1_p + h2_p - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(h_mean - 30))
        + 0.24 * math.cos(math.radians(2 * h_mean))
        + 0.32 * math.cos(math.radians(3 * h_mean + 6))
        - 0.20 * math.cos(math.radians(4 * h_mean - 63))
    )
    s_l = 1 + 0.015 * (l_mean - 50) ** 2 / math.sqrt(20 + (l_mean - 50) ** 2)
    s_c = 1 + 0.045 * c_p_mean
    s_h = 1 + 0.015 * c_p_mean * t
    delta_theta = 30 * math.exp(-(((h_mean - 275) / 25) ** 2))
    r_c = 2 * math.sqrt(c_p_mean**7 / (c_p_mean**7 + 25**7))
    r_t = -r_c * math.sin(math.radians(2 * delta_theta))

    return math.sqrt(
        (dl / s_l) ** 2
        + (dc / s_c) ** 2
        + (dh / s_h) ** 2
        + r_t * (dc / s_c) * (dh / s_h)
    )


def nearest(colour: RGB, palette: list[RGB]) -> tuple[RGB, float]:
    """The closest palette colour and how far away it is."""
    lab = rgb_to_lab(colour)
    distances = [(delta_e_2000(lab, rgb_to_lab(entry)), entry) for entry in palette]
    distance, entry = min(distances)
    return entry, distance
