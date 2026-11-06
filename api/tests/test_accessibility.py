"""Accessibility checks are pure code, so these pin exact numbers."""

from io import BytesIO
from pathlib import Path

import pytest
from app.checks.accessibility import WCAG_RULE_IDS, check_accessibility
from app.checks.accessibility.checks import (
    _standout,
    check_chunk_contrast,
    check_docx,
    check_html,
    check_image_contrast,
)
from app.checks.accessibility.contrast import (
    contrast_ratio,
    nearest_passing,
    parse_colour,
    required_ratio,
)
from app.contracts import CheckType
from app.engine.checks import CheckContext
from app.engine.chunking import chunk_document
from app.engine.parsers import parse
from PIL import Image, ImageDraw

DEMO = Path(__file__).resolve().parents[2] / "demo"
INK = (18, 52, 59)
WHITE = (255, 255, 255)


def ctx():
    return CheckContext(review_id="r1", content_version_id="v1", channel="blog")


def html_chunks(html):
    return chunk_document(parse(html, "html"), "v1", data_class="public")


def explanations(findings):
    return [finding.explanation for finding in findings]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#fff", WHITE),
        ("#12343B", INK),
        ("white", WHITE),
        ("rgb(18, 52, 59)", INK),
        ("rgba(18, 52, 59, 0.5)", INK),
        ("papayawhip", None),
        ("#12", None),
        ("", None),
        (None, None),
    ],
)
def test_colours_are_read_or_refused(value, expected):
    assert parse_colour(value) == expected


def test_contrast_matches_the_wcag_reference_values():
    assert contrast_ratio((0, 0, 0), WHITE) == pytest.approx(21.0)
    assert contrast_ratio(WHITE, WHITE) == pytest.approx(1.0)
    assert contrast_ratio((119, 119, 119), WHITE) == pytest.approx(4.48, abs=0.01)


def test_contrast_ignores_which_colour_comes_first():
    assert contrast_ratio(INK, WHITE) == contrast_ratio(WHITE, INK)


@pytest.mark.parametrize(
    ("font_pt", "bold", "ratio"),
    [
        (None, False, 4.5),
        (12, False, 4.5),
        (17.9, False, 4.5),
        (18, False, 3.0),
        (14, True, 3.0),
        (13.9, True, 4.5),
    ],
)
def test_large_text_needs_less_contrast(font_pt, bold, ratio):
    assert required_ratio(font_pt, bold=bold) == ratio


def test_the_nearest_passing_palette_colour_is_suggested():
    palette = [(238, 242, 239), INK, (95, 111, 107)]

    assert nearest_passing((170, 170, 170), WHITE, palette, 4.5) == (95, 111, 107)


def test_no_suggestion_when_nothing_in_the_palette_passes():
    assert nearest_passing((200, 200, 200), WHITE, [(238, 242, 239)], 4.5) is None


def test_low_contrast_text_is_flagged_with_its_pair_and_a_fix():
    chunks = html_chunks('<p style="color:#aaaaaa;background-color:#ffffff">Hello there</p>')

    findings = check_chunk_contrast(chunks, ctx(), [INK])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "WCAG-1.4.3"
    assert finding.check is CheckType.accessibility
    assert finding.tier == 0
    assert finding.ai_generated is False
    assert finding.cited_text
    assert "#AAAAAA on #FFFFFF" in finding.explanation
    assert "#12343B from the palette passes" in finding.explanation
    assert finding.spans[0].end == len("Hello there")
    preview = finding.trace.steps[-1]
    assert preview.tool == "contrast_preview"
    assert preview.input_summary == "#AAAAAA on #FFFFFF"
    assert preview.output_summary.endswith("try #12343B")


def test_good_contrast_passes():
    chunks = html_chunks('<p style="color:#12343B;background-color:#ffffff">Hello</p>')

    assert check_chunk_contrast(chunks, ctx()) == []


def test_large_text_gets_the_lower_threshold():
    html = '<p style="color:#777777;background-color:#ffffff;font-size:24pt">Big</p>'

    assert check_chunk_contrast(html_chunks(html), ctx()) == []


def test_text_with_no_colours_set_is_left_alone():
    assert check_chunk_contrast(html_chunks("<p>Plain</p>"), ctx()) == []


def test_one_missing_colour_falls_back_to_the_browser_default():
    chunks = html_chunks('<p style="color:#cccccc">Pale on the default white</p>')

    assert len(check_chunk_contrast(chunks, ctx())) == 1


@pytest.mark.parametrize(
    "html",
    [
        '<p style="color:#ffffff;background-color:#ffffff">Hidden trick</p>',
        '<p style="display:none;color:#cccccc">Not shown</p>',
    ],
)
def test_hidden_text_belongs_to_the_hidden_content_check(html):
    assert check_chunk_contrast(html_chunks(html), ctx()) == []


@pytest.mark.parametrize(
    ("tag", "problem"),
    [
        ('<img src="a.png">', "has no alt text"),
        ('<img src="a.png" alt="">', "has empty alt text"),
        ('<img src="a.png" alt="   ">', "has empty alt text"),
        ('<img src="a.png" alt="team-photo.PNG">', "file name"),
        ('<img src="a.png" alt="image">', "meaningless"),
        ('<img src="a.png" alt="1234">', "meaningless"),
    ],
)
def test_bad_alt_text_is_flagged(tag, problem):
    html = f"<p>Copy</p>{tag}"
    findings = check_html(html, html_chunks(html), ctx())

    assert len(findings) == 1
    assert findings[0].rule_id == "WCAG-1.1.1"
    assert problem in findings[0].explanation
    assert findings[0].spans == []


@pytest.mark.parametrize(
    "tag",
    [
        '<img src="a.png" alt="A new hire meeting the team">',
        '<img src="line.png" alt="" role="presentation">',
    ],
)
def test_good_or_decorative_images_pass(tag):
    html = f"<p>Copy</p>{tag}"

    assert check_html(html, html_chunks(html), ctx()) == []


def test_a_skipped_heading_level_is_flagged():
    html = "<h1>Title</h1><h3>Too deep</h3>"
    findings = check_html(html, html_chunks(html), ctx())

    assert [finding.rule_id for finding in findings] == ["WCAG-1.3.1"]
    assert "skips from level 1 to level 3" in findings[0].explanation
    assert findings[0].spans


def test_two_top_level_headings_are_flagged():
    html = "<h1>One</h1><h1>Two</h1>"
    findings = check_html(html, html_chunks(html), ctx())

    assert len(findings) == 1
    assert '"Two"' in findings[0].explanation


def test_headings_in_order_pass():
    html = "<h1>One</h1><h2>Two</h2><h3>Three</h3><h2>Back up</h2>"

    assert check_html(html, html_chunks(html), ctx()) == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Click here", "doesn't say where"),
        ("read more.", "doesn't say where"),
        ("https://tarnhollow.example/landing", "bare web address"),
        ("www.tarnhollow.example", "bare web address"),
    ],
)
def test_vague_links_are_flagged(text, problem):
    html = f'<p>See <a href="/x">{text}</a> now</p>'
    findings = check_html(html, html_chunks(html), ctx())

    assert [finding.rule_id for finding in findings] == ["WCAG-2.4.4"]
    assert problem in findings[0].explanation


def test_a_descriptive_link_passes():
    html = '<p><a href="/x">Read the onboarding guide</a></p>'

    assert check_html(html, html_chunks(html), ctx()) == []


def test_every_finding_cites_a_known_criterion():
    html = (
        '<h1>One</h1><h3>Two</h3><img src="a.png"><p style="color:#ccc">Pale</p>'
        '<a href="/x">here</a>'
    )
    findings = check_accessibility(html, "html", html_chunks(html), ctx())

    assert {finding.rule_id for finding in findings} == WCAG_RULE_IDS


def test_findings_are_stable_between_runs():
    html = '<h1>One</h1><h3>Two</h3><img src="a.png">'
    chunks = html_chunks(html)

    first = check_accessibility(html, "html", chunks, ctx())
    second = check_accessibility(html, "html", chunks, ctx())

    assert [finding.id for finding in first] == [finding.id for finding in second]


def test_the_linkedin_demo_only_raises_wcag_findings():
    data = (DEMO / "pieces" / "linkedin-post.html").read_bytes()
    chunks = chunk_document(parse(data, "html"), "v1", data_class="public")

    findings = check_accessibility(data, "html", chunks, ctx())

    assert all(finding.rule_id in WCAG_RULE_IDS for finding in findings)


def docx_with(paragraphs):
    from docx import Document

    document = Document()
    for text, style in paragraphs:
        document.add_paragraph(text, style=style)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def picture_docx(alt):
    from docx import Document

    image = BytesIO()
    Image.new("RGB", (10, 10), INK).save(image, "PNG")
    image.seek(0)
    document = Document()
    shape = document.add_picture(image)
    doc_pr = shape._inline.docPr
    if alt is None:
        doc_pr.attrib.pop("descr", None)
    else:
        doc_pr.set("descr", alt)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_headings_are_checked():
    data = docx_with([("Top", "Heading 1"), ("Too deep", "Heading 3")])

    findings = check_docx(data, [], ctx())

    assert [finding.rule_id for finding in findings] == ["WCAG-1.3.1"]


def test_a_docx_picture_needs_alt_text():
    findings = check_docx(picture_docx(None), [], ctx())

    assert [finding.rule_id for finding in findings] == ["WCAG-1.1.1"]


def test_a_docx_picture_with_alt_text_passes():
    assert check_docx(picture_docx("A team at a whiteboard"), [], ctx()) == []


def banner(text_colour, background=WHITE):
    image = Image.new("RGB", (300, 80), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 200, 56), fill=text_colour)
    draw.rectangle((30, 30, 190, 46), fill=background)
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def fake_ocr(image):
    return [
        {"left": 20, "top": 20, "right": 200, "bottom": 56, "text": "Headline"},
    ]


def test_image_text_is_measured_from_its_box():
    findings = check_image_contrast(
        banner((200, 200, 200)), [], ctx(), [INK], ocr=fake_ocr
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "WCAG-1.4.3"
    assert '"Headline"' in findings[0].explanation


def test_strong_image_text_passes():
    assert check_image_contrast(banner(INK), [], ctx(), ocr=fake_ocr) == []


def test_an_image_with_no_text_has_nothing_to_measure():
    assert check_image_contrast(banner(INK), [], ctx(), ocr=lambda image: []) == []


def test_faint_text_becomes_solid_for_ocr():
    image = Image.new("RGB", (60, 20), (18, 53, 59))
    image.paste((44, 103, 78), (10, 5, 50, 15))

    mask = _standout(image)

    assert mask.size == (120, 40)
    assert mask.getpixel((60, 20)) == 0
    assert mask.getpixel((2, 2)) == 255
