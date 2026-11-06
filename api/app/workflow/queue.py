"""What's waiting for a reviewer."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import engine as engine_client
from app.content.access import latest_review
from app.content.models import Content
from app.contracts import ContentState, Finding, FindingStatus, Severity, Verdict
from app.workflow.decisions import FindingProgress, finding_progress
from app.workflow.schemas import QueueItem

SEVERITY_ORDER = [Severity.critical, Severity.high, Severity.medium, Severity.low]
REVIEWER_STATES = (ContentState.resolving.value, ContentState.reviewer_check.value)


def _kind_of(finding: Finding, standing: FindingProgress) -> str | None:
    if standing.status is FindingStatus.override_pending:
        return "override"
    if standing.status is FindingStatus.fix_edited:
        return "fix"
    if finding.verdict is Verdict.UNSURE and standing.status is FindingStatus.open:
        return "unsure"
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
                reason=standing.reason,
                fix_text=standing.fix_text,
            )
        )
    return items


def reviewer_queue(session: Session) -> list[QueueItem]:
    """UNSURE findings and pending overrides, most serious first."""
    contents = session.scalars(
        select(Content).where(Content.state.in_(REVIEWER_STATES))
    ).all()
    items = [item for content in contents for item in _items_for(session, content)]
    return sorted(
        items, key=lambda item: (SEVERITY_ORDER.index(item.severity), item.title)
    )
