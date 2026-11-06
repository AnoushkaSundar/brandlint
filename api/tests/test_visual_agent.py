"""The Visual agent, measured on the real demo banner and logo."""

import json
from io import BytesIO
from pathlib import Path

import pytest
from app.checks.visual.checks import (
    VisualBrand,
    _bgr,
    check_imagery,
    check_logo,
    check_palette,
    check_visual,
    dominant_colours,
    find_logo,
)
from app.checks.visual.colour import delta_e_2000, nearest, rgb_to_lab
from app.contracts import Rule, Verdict
from app.engine.checks import CheckContext
from PIL import Image

DEMO = Path(__file__).resolve().parents[2] / "demo"
BANNER = (DEMO / "pieces" / "banner.png").read_bytes()
LOGO = (DEMO / "brand" / "logo.png").read_bytes()
RULES = [
    Rule.model_validate(rule)
    for rule in json.loads((DEMO / "brand" / "rules.json").read_text(encoding="utf-8"))
]
ASSETS = json.loads((DEMO / "brand" / "assets.json").read_text(encoding="utf-8"))
PALETTE = [
    tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))
    for value in next(a for a in ASSETS if a["kind"] == "palette")["meta"]["colours"]
]
BRAND = VisualBrand(PALETTE, [LOGO])
MODEL = "claude-haiku-4-5"


def ctx(channel="banner", rules=RULES):
    return CheckContext(review_id="r1", content_version_id="v1", channel=channel, rules=rules)


def png(image):
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def placed_logo(*, x_stretch=1.0, y_stretch=1.0, rotate=0.0, background=(238, 242, 239)):
    logo = Image.open(BytesIO(LOGO)).convert("RGBA")
    width, height = round(logo.width * x_stretch), round(logo.height * y_stretch)
    logo = logo.resize((width, height), Image.Resampling.LANCZOS)
    if rotate:
        logo = logo.rotate(rotate, expand=True, resample=Image.Resampling.BICUBIC)
    canvas = Image.new("RGB", (logo.width + 160, logo.height + 160), background)
    canvas.paste(logo, (80, 80), logo)
    return png(canvas)


def passing(*args):
    return {"verdicts": [{"rule_id": "R-VIS-03", "verdict": "PASS", "confidence": 0.9, "explanation": "Fine."}]}


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
        ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
        ((50.0, 2.5, 0.0), (61.0, -5.0, 29.0), 22.8977),
        ((50.0, 2.5, 0.0), (50.0, 0.0, -2.5), 4.3065),
        ((2.0776, 0.0795, -1.135), (0.9033, -0.0636, -0.5514), 0.9082),
    ],
)
def test_delta_e_matches_the_published_ciede2000_data(first, second, expected):
    assert delta_e_2000(first, second) == pytest.approx(expected, abs=0.0001)


def test_identical_colours_have_no_distance():
    lab = rgb_to_lab((18, 52, 59))

    assert delta_e_2000(lab, lab) == 0


def test_nearest_finds_the_closest_palette_colour():
    entry, distance = nearest((20, 54, 60), PALETTE)

    assert entry == (0x12, 0x34, 0x3B)
    assert distance < 2


def test_the_banners_stretched_logo_is_flagged():
    findings = check_logo(BANNER, ctx(), BRAND)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "R-VIS-01"
    assert finding.tier == 0
    assert finding.cited_text
    assert "stretched" in finding.explanation
    assert "wider" in finding.explanation


def test_the_measured_stretch_is_close_to_the_real_one():
    match = find_logo(_bgr(BANNER), _bgr(LOGO, dominant_colours(BANNER)[0][0]))

    assert match is not None
    assert match.distortion == pytest.approx(0.5, abs=0.1)


def test_a_logo_at_its_true_proportions_passes():
    assert check_logo(placed_logo(), ctx(), BRAND) == []


def test_a_logo_within_the_tolerance_passes():
    assert check_logo(placed_logo(x_stretch=1.01), ctx(), BRAND) == []


@pytest.mark.parametrize("stretch", [1.1, 1.25, 1.5])
def test_the_measured_stretch_is_accurate(stretch):
    image = placed_logo(x_stretch=stretch)

    match = find_logo(_bgr(image), _bgr(LOGO, (238, 242, 239)))

    expected = max(stretch, 1 / stretch) - 1
    assert match.distortion == pytest.approx(expected, abs=0.05)


def test_a_squashed_logo_is_flagged():
    findings = check_logo(placed_logo(x_stretch=0.75), ctx(), BRAND)

    assert len(findings) == 1
    assert "taller" in findings[0].explanation


def test_a_rotated_logo_is_flagged():
    findings = check_logo(placed_logo(rotate=20), ctx(), BRAND)

    assert len(findings) == 1
    assert "rotated" in findings[0].explanation


def test_an_image_without_the_logo_has_nothing_to_flag():
    assert check_logo(png(Image.new("RGB", (400, 200), (238, 242, 239))), ctx(), BRAND) == []


def test_no_logo_rule_in_the_rulebook_means_no_flag():
    rules = [rule for rule in RULES if rule.id != "R-VIS-01"]

    assert check_logo(BANNER, ctx(rules=rules), BRAND) == []


def test_a_channel_outside_the_rules_scope_is_not_checked():
    assert check_logo(BANNER, ctx(channel="blog"), BRAND) == []


def test_the_banners_off_palette_colour_is_flagged():
    findings = check_palette(BANNER, ctx(), BRAND)

    assert findings
    assert all(finding.rule_id == "R-VIS-02" for finding in findings)
    assert any("#FF2EC4" in finding.explanation for finding in findings)


def test_palette_colours_pass():
    image = Image.new("RGB", (120, 60), PALETTE[0])
    image.paste(PALETTE[1], (60, 0, 120, 60))

    assert check_palette(png(image), ctx(), BRAND) == []


def test_a_colour_just_inside_the_limit_passes():
    red, green, blue = PALETTE[0]
    image = Image.new("RGB", (60, 60), (red + 2, green + 2, blue + 2))

    assert check_palette(png(image), ctx(), BRAND) == []


def test_the_limit_can_be_changed():
    image = Image.new("RGB", (60, 60), (40, 80, 90))

    assert check_palette(png(image), ctx(), BRAND, limit=50) == []
    assert check_palette(png(image), ctx(), BRAND, limit=1)


def test_dominant_colours_cover_the_image():
    image = Image.new("RGB", (100, 100), (255, 0, 0))
    image.paste((0, 0, 255), (0, 0, 25, 100))

    colours = dominant_colours(png(image))

    assert colours[0][0] == (255, 0, 0)
    assert colours[0][1] == pytest.approx(0.75, abs=0.02)


def test_a_clean_imagery_verdict_adds_nothing():
    assert check_imagery(BANNER, "public", ctx(), passing, model=MODEL) == []


def test_an_imagery_violation_is_an_ai_finding_citing_the_rule():
    def reply(*args):
        return {
            "verdicts": [
                {
                    "rule_id": "R-VIS-03",
                    "verdict": "VIOLATION",
                    "confidence": 0.8,
                    "explanation": "This looks like a generated face.",
                }
            ]
        }

    finding = check_imagery(BANNER, "public", ctx(), reply, model=MODEL)[0]

    assert finding.rule_id == "R-VIS-03"
    assert finding.tier == 1
    assert finding.ai_generated is True
    assert finding.models_used == [MODEL]
    assert finding.trace.model == MODEL
    assert finding.confidence == 0.8


@pytest.mark.parametrize(
    "reply",
    [
        5,
        None,
        [1],
        {},
        {"verdicts": []},
        {"content": "not json"},
        {"verdicts": [{"rule_id": "R-OTHER", "verdict": "PASS", "confidence": 1, "explanation": "x"}]},
        {"verdicts": [{"rule_id": "R-VIS-03", "verdict": "MAYBE", "confidence": 1, "explanation": "x"}]},
    ],
)
def test_a_bad_reply_goes_to_a_reviewer_not_a_pass(reply):
    findings = check_imagery(BANNER, "public", ctx(), lambda *a: reply, model=MODEL)

    assert [finding.verdict for finding in findings] == [Verdict.UNSURE]
    assert findings[0].confidence == 0


def test_a_gateway_failure_goes_to_a_reviewer():
    def refuse(*args):
        raise ValueError("confidential visuals can't be masked")

    findings = check_imagery(BANNER, "confidential", ctx(), refuse, model=MODEL)

    assert [finding.verdict for finding in findings] == [Verdict.UNSURE]


def test_the_data_class_and_rule_reach_the_gateway():
    calls = []

    def record(data_class, rule_ids, payload, review_id):
        calls.append((data_class, rule_ids, review_id))
        return passing()

    check_imagery(BANNER, "internal", ctx(), record, model=MODEL)

    assert calls == [("internal", ["R-VIS-03"], "r1")]


def test_the_whole_agent_finds_the_planted_banner_problems():
    findings = check_visual(BANNER, "public", ctx(), BRAND, passing, model=MODEL)

    assert {"R-VIS-01", "R-VIS-02"} <= {finding.rule_id for finding in findings}
    assert all(finding.cited_text for finding in findings)


def test_findings_are_stable_between_runs():
    first = check_visual(BANNER, "public", ctx(), BRAND, passing, model=MODEL)
    second = check_visual(BANNER, "public", ctx(), BRAND, passing, model=MODEL)

    assert [f.explanation for f in first] == [f.explanation for f in second]
