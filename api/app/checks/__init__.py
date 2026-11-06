"""Checks that need the original file, not just its chunks.

The engine calls `run_product_checks` from a graph track and treats the result like
any other findings. Rule ids in `PRODUCT_RULE_IDS` have to be known to the critic.
"""

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.checks.accessibility import WCAG_RULE_IDS, check_accessibility
from app.checks.visual import check_visual, load_visual_brand
from app.contracts import Finding
from app.engine.checks.context import CheckContext
from app.engine.chunking import ParsedChunk

PRODUCT_RULE_IDS = WCAG_RULE_IDS


def run_product_checks(
    data: bytes | str,
    fmt: str,
    chunks: Sequence[ParsedChunk],
    ctx: CheckContext,
    *,
    data_class: str,
    session_factory: Callable[[], Session],
    classify: Callable[[str, list[str], dict[str, Any], str], dict[str, Any]],
    model: str,
) -> list[Finding]:
    """Accessibility for every format, and the Visual agent for images."""
    with session_factory() as session:
        brand = load_visual_brand(session)
    findings = check_accessibility(data, fmt, chunks, ctx, brand.palette)
    if fmt == "image" and isinstance(data, bytes):
        findings += check_visual(data, data_class, ctx, brand, classify, model=model)
    return findings
