"""Who may do what to a finding. The server enforces this and the UI reads it."""

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.models import User
from app.clients import engine as engine_client
from app.content.models import Content, ContentVersion
from app.contracts import (
    ContentState,
    DecisionAction,
    Finding,
    FindingStatus,
    Role,
    Severity,
    Verdict,
)
from app.tenancy import scoped
from app.workflow.fixes import can_apply, fix_span, latest_offer, spans_overlap
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
# Replaced by what a later decision writes, so only a sign-off keeps the wording.
KEEPS_FIX_TEXT = DecisionAction.resolve.value

FindingKey = tuple[str | None, str, str]


@dataclass(frozen=True)
class FindingProgress:
    status: FindingStatus = FindingStatus.open
    fix_text: str | None = None
    reason: str | None = None


def finding_progress(session: Session, review: Review) -> dict[str, FindingProgress]:
    """The newest decision on each finding in a review decides where it stands."""
    decisions = session.scalars(
        scoped(session, Decision)
        .where(Decision.review_id == review.id)
        .order_by(Decision.created_at)
    )
    progress: dict[str, FindingProgress] = {}
    for decision in decisions:
        earlier = progress.get(decision.finding_id, FindingProgress())
        kept = earlier.fix_text if decision.action == KEEPS_FIX_TEXT else None
        progress[decision.finding_id] = FindingProgress(
            status=FindingStatus(decision.status),
            # An empty string is a real fix: it deletes the phrase.
            fix_text=decision.fix_text if decision.fix_text is not None else kept,
            reason=decision.reason,
        )
    return progress


def finding_key(finding: Finding) -> FindingKey:
    """Finding ids change with each review, so an issue is matched by what it cites."""
    return (finding.rule_id, finding.check.value, finding.cited_text)


def refused_overrides(session: Session, content_id: str) -> set[FindingKey]:
    """Issues whose override a reviewer rejected, on any review of this content."""
    rows = session.execute(
        scoped(session, Decision, Decision.finding_id, Review.engine_review_id)
        .scoped_join(session, Review, Decision.review_id == Review.id)
        .scoped_join(session, ContentVersion, Review.content_version_id == ContentVersion.id)
        .where(
            ContentVersion.content_id == content_id,
            Decision.status == FindingStatus.override_rejected.value,
        )
    ).all()

    rejected: dict[str, set[str]] = defaultdict(set)
    for finding_id, engine_review_id in rows:
        rejected[engine_review_id].add(finding_id)
    return {
        finding_key(finding)
        for engine_review_id, finding_ids in rejected.items()
        for finding in engine_client.list_findings(engine_review_id)
        if finding.id in finding_ids
    }


def allowed_actions(
    finding: Finding,
    finding_status: FindingStatus,
    user: User,
    content: Content,
    refused: Collection[FindingKey] = (),
) -> set[DecisionAction]:
    if user.role == Role.reviewer.value and content.state in REVIEWER_STATES:
        return _reviewer_actions(finding, finding_status)
    is_owner = user.role == Role.creator.value and content.creator_id == user.id
    if is_owner and content.state == ContentState.resolving.value:
        return _creator_actions(finding, finding_status, refused)
    return set()


def _reviewer_actions(
    finding: Finding, finding_status: FindingStatus
) -> set[DecisionAction]:
    if finding_status is FindingStatus.override_pending:
        return {DecisionAction.confirm_override, DecisionAction.reject_override}
    # A person's wording, or a fix covering part of a claim, needs a second pair of eyes.
    if finding_status is FindingStatus.fix_edited:
        return {DecisionAction.resolve, DecisionAction.reject_override}
    if finding_status not in UNDECIDED:
        return set()
    if finding.verdict is Verdict.UNSURE:
        return {DecisionAction.resolve}
    return {DecisionAction.override}


def _creator_actions(
    finding: Finding,
    finding_status: FindingStatus,
    refused: Collection[FindingKey],
) -> set[DecisionAction]:
    # An UNSURE finding is only ever a reviewer's to settle.
    if finding.verdict is not Verdict.VIOLATION or finding_status not in UNDECIDED:
        return set()
    actions: set[DecisionAction] = set()
    if finding.fix_available:
        actions |= FIXES
    # A rejected override stays rejected, even through a new review.
    may_override = (
        finding_status is FindingStatus.open
        and finding.severity in CREATOR_OVERRIDABLE
        and finding_key(finding) not in refused
    )
    if may_override:
        actions.add(DecisionAction.override)
    return actions


def _status_after(
    action: DecisionAction,
    actor: User,
    finding: Finding,
    before: FindingStatus,
) -> FindingStatus:
    # A rejected fix reopens the finding. It wasn't an override, so none is refused.
    if action is DecisionAction.reject_override and before is FindingStatus.fix_edited:
        return FindingStatus.open
    if action is DecisionAction.override:
        return (
            FindingStatus.override_confirmed
            if actor.role == Role.reviewer.value
            else FindingStatus.override_pending
        )
    if action is DecisionAction.accept_fix:
        # A fix rewrites one span, so the rest of a split claim still needs checking.
        whole = sum(span.end > span.start for span in finding.spans) <= 1
        return FindingStatus.fix_accepted if whole else FindingStatus.fix_edited
    return {
        DecisionAction.edit_fix: FindingStatus.fix_edited,
        DecisionAction.confirm_override: FindingStatus.override_confirmed,
        DecisionAction.reject_override: FindingStatus.override_rejected,
        DecisionAction.resolve: FindingStatus.resolved,
    }[action]


def _overlaps_a_fix(
    finding: Finding,
    findings: Sequence[Finding],
    progress: dict[str, FindingProgress],
) -> bool:
    span = fix_span(finding)
    if span is None:
        return False
    for other in findings:
        other_span = fix_span(other)
        has_fix = progress.get(other.id, FindingProgress()).fix_text is not None
        is_other = other.id != finding.id
        if is_other and has_fix and other_span and spans_overlap(span, other_span):
            return True
    return False


def record_decision(
    session: Session,
    *,
    content: Content,
    review: Review,
    finding: Finding,
    findings: Sequence[Finding],
    actor: User,
    action: DecisionAction,
    reason: str | None,
    fix_text: str | None,
    attempt: int | None = None,
) -> FindingStatus:
    """Checks and stores a decision and its audit entry. The caller commits."""
    reason = (reason or "").strip() or None
    fix_text = (fix_text or "").strip() or None
    if action in NEEDS_REASON and reason is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a reason for this decision."
        )
    if action is DecisionAction.edit_fix and fix_text is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "An edited fix needs its text."
        )

    progress = finding_progress(session, review)
    before = progress.get(finding.id, FindingProgress()).status
    refused = refused_overrides(session, content.id)
    if action not in allowed_actions(finding, before, actor, content, refused):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can't do that to this finding."
        )

    if action is DecisionAction.accept_fix:
        # The wording always comes from the engine's offer, never from the request.
        offer = latest_offer(session, review, finding.id)
        if offer is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Ask for a fix first.")
        # The wording on the person's screen has to be the wording that's saved.
        if attempt != offer.attempt:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A newer fix was offered. Check it first."
            )
        fix_text = offer.suggested
    chunks = engine_client.list_chunks(review.engine_review_id) if action in FIXES else []
    if action in FIXES and not can_apply(finding, chunks):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A fix can't change this text. A reviewer needs to settle it.",
        )
    if action in FIXES and _overlaps_a_fix(finding, findings, progress):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This overlaps a fix already saved. A reviewer needs to settle it.",
        )

    after = _status_after(action, actor, finding, before)
    session.add(
        Decision(
            review_id=review.id,
            finding_id=finding.id,
            actor_id=actor.id,
            role=actor.role,
            action=action.value,
            status=after.value,
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
    query = scoped(session, Decision).order_by(Decision.created_at)
    if since is not None:
        query = query.where(Decision.created_at >= since)
    return session.scalars(query).all()
