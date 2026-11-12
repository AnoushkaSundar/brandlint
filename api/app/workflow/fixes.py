"""Fix offers from the engine, and turning approved fixes into a new version."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.models import User
from app.clients import engine as engine_client
from app.content.models import Content, ContentVersion
from app.contracts import Chunk, Finding, FixSuggestion, Span
from app.tenancy import bound_org, scoped
from app.workflow.models import FixOffer, Review

MAX_FIX_ATTEMPTS = 2
NO_SAFE_FIX = "No safe fix found; marked for review"
HIDDEN_FONT_PT = 4


class HasFixText(Protocol):
    fix_text: str | None


class FixCannotApply(ValueError):
    """A saved fix has nowhere to go. Decisions refuse this before it's stored."""


class FixesOverlap(FixCannotApply):
    """Two saved fixes rewrite the same text."""


def _offers(session: Session, review: Review, finding_id: str) -> list[FixOffer]:
    return list(
        session.scalars(
            scoped(session, FixOffer)
            .where(FixOffer.review_id == review.id, FixOffer.finding_id == finding_id)
            .order_by(FixOffer.attempt)
        )
    )


def latest_offer(session: Session, review: Review, finding_id: str) -> FixOffer | None:
    offers = _offers(session, review, finding_id)
    return offers[-1] if offers else None


def _suggestion(offer: FixOffer) -> FixSuggestion:
    return FixSuggestion(
        finding_id=offer.finding_id,
        original=offer.original,
        suggested=offer.suggested,
        diff=offer.diff,
        attempt=offer.attempt,
    )


def offer_fix(
    session: Session, review: Review, finding_id: str, *, again: bool
) -> FixSuggestion:
    """Returns the stored suggestion, or asks the engine for a new one if `again`.

    Reopening a panel therefore never spends one of the two attempts. The caller commits.
    """
    offers = _offers(session, review, finding_id)
    if offers and not again:
        return _suggestion(offers[-1])
    if len(offers) >= MAX_FIX_ATTEMPTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, NO_SAFE_FIX)

    suggestion = engine_client.request_fix(
        finding_id, len(offers) + 1, org_id=bound_org(session)
    )
    session.add(
        FixOffer(
            review_id=review.id,
            finding_id=finding_id,
            attempt=suggestion.attempt,
            original=suggestion.original,
            suggested=suggestion.suggested,
            diff=suggestion.diff,
        )
    )
    return suggestion


def is_readable(chunk: Chunk) -> bool:
    """Whether a person reads this as copy. Matches the engine's hidden check.

    Zero-width characters aren't here: emoji and several scripts need them.
    """
    style = chunk.style or {}
    color, background = style.get("color"), style.get("background")
    font_pt = style.get("font_pt")
    return not (
        chunk.kind == "image"
        or style.get("hidden")
        or style.get("from_comment")
        or style.get("from_metadata")
        or style.get("from_ocr")
        or (color and background and color.lower() == background.lower())
        or (font_pt is not None and font_pt < HIDDEN_FONT_PT)
    )


def fix_span(finding: Finding) -> Span | None:
    """The span a fix rewrites. Empty spans mark no text, so they don't count."""
    spans = [span for span in finding.spans if span.end > span.start]
    return spans[-1] if spans else None


def spans_overlap(first: Span, second: Span) -> bool:
    return (
        first.chunk_id == second.chunk_id
        and first.start < second.end
        and second.start < first.end
    )


def can_apply(finding: Finding, chunks: Sequence[Chunk]) -> bool:
    """Whether a fix for this finding would reach text a person reads."""
    span = fix_span(finding)
    if span is None:
        return True
    target = next((chunk for chunk in chunks if chunk.id == span.chunk_id), None)
    return target is not None and is_readable(target)


def text_with_fixes(
    chunks: Sequence[Chunk],
    findings: Iterable[Finding],
    progress: Mapping[str, HasFixText],
) -> str:
    """Rebuilds the text with each fix in place. Spans are offsets within a chunk.

    Only readable chunks are included, because hidden text must never come back as
    ordinary copy for the manager and legal.
    """
    edits: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    additions: list[str] = []
    for finding in findings:
        standing = progress.get(finding.id)
        if standing is None or standing.fix_text is None:
            continue
        span = fix_span(finding)
        if span is None:
            # A document-level fix has nowhere to go, such as a missing disclaimer.
            if standing.fix_text:
                additions.append(standing.fix_text)
        else:
            edits[span.chunk_id].append((span.start, span.end, standing.fix_text))

    parts = []
    for chunk in sorted(chunks, key=lambda item: item.ordinal):
        if not is_readable(chunk):
            if edits[chunk.id]:
                raise FixCannotApply(chunk.id)
            continue
        text = chunk.text
        limit = len(text)
        # Right to left, so one edit never shifts the offsets of the next.
        for start, end, fix_text in sorted(edits[chunk.id], reverse=True):
            if end > limit:
                raise FixesOverlap(chunk.id)
            text = text[:start] + fix_text + text[end:]
            limit = start
        parts.append(text)
    return "\n\n".join([*parts, *additions])


def save_fixed_version(
    session: Session, content: Content, text: str, actor: User
) -> ContentVersion | None:
    """Adds a version with the fixes applied, unless the newest already has this text.

    The upload carries over, because fixes can't be written into a DOCX or a PDF.
    """
    latest = session.scalar(
        scoped(session, ContentVersion)
        .where(ContentVersion.content_id == content.id)
        .order_by(ContentVersion.version.desc())
        .limit(1)
    )
    if latest is not None and latest.text == text:
        return None
    version = ContentVersion(
        content_id=content.id,
        version=(latest.version if latest else 0) + 1,
        text=text,
        file_ref=latest.file_ref if latest else None,
        file_name=latest.file_name if latest else None,
        fixes_applied=True,
        created_by=actor.id,
    )
    session.add(version)
    return version
