"""What's waiting for a reviewer."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import engine as engine_client
from app.content.access import latest_review
from app.content.models import Content
from app.contracts import ContentState, Finding, FindingStatus, Severity, Verdict
from app.workflow.decisions import FindingProgress, finding_progress
from app.workflow.schemas import QueueItem

logger = logging.getLogger(__name__)

SEVERITY_ORDER = [Severity.critical, Severity.high, Severity.medium, Severity.low]
ONLY_A_REVIEWER = {Severity.high, Severity.critical}
REVIEWER_STATES = (ContentState.resolving.value, ContentState.reviewer_check.value)


def _kind_of(finding: Finding, standing: FindingProgress) -> str | None:
    if standing.status is FindingStatus.override_pending:
        return "override"
    if standing.status is FindingStatus.fix_edited:
        return "fix"
    if finding.verdict is Verdict.UNSURE and standing.status is FindingStatus.open:
        return "unsure"
    if finding.verdict is not Verdict.VIOLATION:
        return None
    # These block the piece, and the creator can't clear them by overriding.
    if standing.status is FindingStatus.open and finding.severity in ONLY_A_REVIEWER:
        return "needs_override"
    if standing.status is FindingStatus.override_rejected and not finding.fix_available:
        return "needs_override"
    return None


def _items_for(session: Session, content: Content) -> list[QueueItem]:
    review = latest_review(session, content.id)
    if review is None:
        return []
    progress = finding_progress(session, review)

    items = []
    for finding in engine_client.list_findings(review.engine_review_id):
        standing = progress.get(finding.id, FindingProgress())
        kind = _kind_of(finding, standing)
        if kind is None:
            continue
        items.append(
            QueueItem(
                content_id=content.id,
                title=content.title,
                channel=content.channel,
                state=ContentState(content.state),
                finding_id=finding.id,
                kind=kind,
                severity=finding.severity,
                check=finding.check,
                explanation=finding.explanation,
                rule_id=finding.rule_id,
                fact_ids=finding.fact_ids,
                cited_text=finding.cited_text,
                reason=standing.reason,
                fix_text=standing.fix_text,
            )
        )
    return items


def reviewer_queue(session: Session) -> tuple[list[QueueItem], list[str]]:
    """What needs a reviewer, most serious first, and any pieces that couldn't load.

    One piece failing mustn't hide everyone else's work, so it's reported and skipped.
    """
    contents = session.scalars(
        select(Content).where(Content.state.in_(REVIEWER_STATES))
    ).all()
    items: list[QueueItem] = []
    unavailable: list[str] = []
    for content in contents:
        try:
            items.extend(_items_for(session, content))
        except Exception:
            logger.exception("couldn't read the queue for %s", content.id)
            unavailable.append(content.title)
    ordered = sorted(
        items, key=lambda item: (SEVERITY_ORDER.index(item.severity), item.title)
    )
    return ordered, unavailable
