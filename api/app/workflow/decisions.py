"""Who may do what to a finding. The server enforces this and the UI reads it."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.models import Content
from app.contracts import (
    ContentState,
    DecisionAction,
    Finding,
    FindingStatus,
    Role,
    Severity,
    Verdict,
)
from app.workflow.models import AuditLog, Decision, Review

CREATOR_OVERRIDABLE = {Severity.low, Severity.medium}
FIXES = {DecisionAction.accept_fix, DecisionAction.edit_fix}
NEEDS_REASON = {
    DecisionAction.override,
    DecisionAction.reject_override,
    DecisionAction.resolve,
}
REVIEWER_STATES = {ContentState.resolving.value, ContentState.reviewer_check.value}
UNDECIDED = {FindingStatus.open, FindingStatus.override_rejected}

STATUS_AFTER = {
    DecisionAction.accept_fix: FindingStatus.fix_accepted,
    DecisionAction.edit_fix: FindingStatus.fix_edited,
    DecisionAction.confirm_override: FindingStatus.override_confirmed,
    DecisionAction.reject_override: FindingStatus.override_rejected,
    DecisionAction.resolve: FindingStatus.resolved,
}


@dataclass(frozen=True)
class FindingProgress:
    status: FindingStatus = FindingStatus.open
    fix_text: str | None = None


def finding_progress(session: Session, review: Review) -> dict[str, FindingProgress]:
    """The newest decision on each finding in a review decides where it stands."""
    decisions = session.scalars(
        select(Decision)
        .where(Decision.review_id == review.id)
        .order_by(Decision.created_at)
    )
    progress: dict[str, FindingProgress] = {}
    for decision in decisions:
        progress[decision.finding_id] = FindingProgress(
            status=_status_after(DecisionAction(decision.action), decision.role),
            fix_text=decision.fix_text,
        )
    return progress


def _status_after(action: DecisionAction, role: str) -> FindingStatus:
    if action is DecisionAction.override:
        return (
            FindingStatus.override_confirmed
            if role == Role.reviewer.value
            else FindingStatus.override_pending
        )
    return STATUS_AFTER[action]


def allowed_actions(
    finding: Finding,
    finding_status: FindingStatus,
    user: User,
    content: Content,
) -> set[DecisionAction]:
    if user.role == Role.reviewer.value and content.state in REVIEWER_STATES:
        return _reviewer_actions(finding, finding_status)
    is_owner = user.role == Role.creator.value and content.creator_id == user.id
    if is_owner and content.state == ContentState.resolving.value:
        return _creator_actions(finding, finding_status)
    return set()


def _reviewer_actions(
    finding: Finding, finding_status: FindingStatus
) -> set[DecisionAction]:
    if finding_status is FindingStatus.override_pending:
        return {DecisionAction.confirm_override, DecisionAction.reject_override}
    if finding_status not in UNDECIDED:
        return set()
    if finding.verdict is Verdict.UNSURE:
        return {DecisionAction.resolve}
    return {DecisionAction.override}


def _creator_actions(
    finding: Finding, finding_status: FindingStatus
) -> set[DecisionAction]:
    # An UNSURE finding is only ever a reviewer's to settle.
    if finding.verdict is not Verdict.VIOLATION or finding_status not in UNDECIDED:
        return set()
    actions: set[DecisionAction] = set()
    if finding.fix_available:
        actions |= FIXES
    # A rejected override can't be raised again, so it has to be fixed.
    if finding_status is FindingStatus.open and finding.severity in CREATOR_OVERRIDABLE:
        actions.add(DecisionAction.override)
    return actions


def record_decision(
    session: Session,
    *,
    content: Content,
    review: Review,
    finding: Finding,
    actor: User,
    action: DecisionAction,
    reason: str | None,
    fix_text: str | None,
) -> FindingStatus:
    """Checks and stores a decision and its audit entry. The caller commits."""
    reason = (reason or "").strip() or None
    fix_text = (fix_text or "").strip() or None
    if action in NEEDS_REASON and reason is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a reason for this decision."
        )
    if action in FIXES and fix_text is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A fix needs its text."
        )

    before = finding_progress(session, review).get(finding.id, FindingProgress()).status
    if action not in allowed_actions(finding, before, actor, content):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can't do that to this finding."
        )

    after = _status_after(action, actor.role)
    session.add(
        Decision(
            review_id=review.id,
            finding_id=finding.id,
            actor_id=actor.id,
            role=actor.role,
            action=action.value,
            reason=reason,
            fix_text=fix_text if action in FIXES else None,
        )
    )
    session.add(
        AuditLog(
            actor_id=actor.id,
            role=actor.role,
            action=f"decision:{action.value}",
            target_type="finding",
            target_id=finding.id,
            before={"status": before.value},
            after={"status": after.value, "reason": reason},
            rulebook_version=review.rulebook_version,
        )
    )
    return after


def list_decisions(session: Session, since: datetime | None = None) -> Sequence[Decision]:
    query = select(Decision).order_by(Decision.created_at)
    if since is not None:
        query = query.where(Decision.created_at >= since)
    return session.scalars(query).all()
