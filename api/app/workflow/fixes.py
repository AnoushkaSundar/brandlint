"""Fix offers from the engine, and turning approved fixes into a new version."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.clients import engine as engine_client
from app.content.models import Content, ContentVersion
from app.contracts import Chunk, Finding, FixSuggestion, Span
from app.workflow.models import FixOffer, Review

MAX_FIX_ATTEMPTS = 2
NO_SAFE_FIX = "No safe fix found; marked for review"


class HasFixText(Protocol):
    fix_text: str | None


class FixesOverlap(ValueError):
    """Two saved fixes rewrite the same text. Decisions refuse this before it's stored."""


def _offers(session: Session, review: Review, finding_id: str) -> list[FixOffer]:
    return list(
        session.scalars(
            select(FixOffer)
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

    suggestion = engine_client.request_fix(finding_id, len(offers) + 1)
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


def text_with_fixes(
    chunks: Sequence[Chunk],
    findings: Iterable[Finding],
    progress: Mapping[str, HasFixText],
) -> str:
    """Rebuilds the text with each fix in place. Spans are offsets within a chunk."""
    edits: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    additions: list[str] = []
    for finding in findings:
        standing = progress.get(finding.id)
        if standing is None or standing.fix_text is None:
            continue
        span = fix_span(finding)
        if span is None:
            # A document-level fix has nowhere to go, such as a missing disclaimer.
            additions.append(standing.fix_text)
        else:
            edits[span.chunk_id].append((span.start, span.end, standing.fix_text))

    parts = []
    for chunk in sorted(chunks, key=lambda item: item.ordinal):
        if chunk.kind == "image":
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
        select(ContentVersion)
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
