"""The content state machine. Every rule here is enforced on the server."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.models import Content
from app.contracts import (
    CheckType,
    ContentState,
    Finding,
    FindingStatus,
    Role,
    Severity,
    Verdict,
)
from app.workflow.decisions import FindingProgress
from app.workflow.transitions import move_content

SERIOUS = {Severity.high, Severity.critical}
FINISHED = {ContentState.published, ContentState.rejected}
REJECTORS = {Role.reviewer, Role.manager}
WAITING_FOR_REVIEWER = {FindingStatus.override_pending, FindingStatus.fix_edited}


@dataclass(frozen=True)
class Move:
    source: ContentState
    target: ContentState
    role: Role
    needs_reason: bool = False


MOVES = (
    Move(ContentState.ai_review, ContentState.resolving, Role.creator),
    Move(ContentState.resolving, ContentState.reviewer_check, Role.creator),
    Move(ContentState.reviewer_check, ContentState.manager_approval, Role.reviewer),
    Move(ContentState.reviewer_check, ContentState.resolving, Role.reviewer, needs_reason=True),
    Move(ContentState.manager_approval, ContentState.legal_signoff, Role.manager),
    Move(ContentState.manager_approval, ContentState.published, Role.manager),
    Move(ContentState.legal_signoff, ContentState.published, Role.legal),
)


@dataclass(frozen=True)
class MoveOption:
    to: ContentState
    needs_reason: bool
    blocked_by: str | None


@dataclass(frozen=True)
class ReviewFacts:
    """What the state machine needs to know about the latest review."""

    findings: Sequence[Finding] = ()
    progress: Mapping[str, FindingProgress] = field(default_factory=dict)
    # running, done, failed or unknown. Only `done` means every check finished.
    run_status: str = "unknown"
    # False once a newer version exists than the one this review looked at.
    covers_latest: bool = False


def needs_legal(findings: Sequence[Finding]) -> bool:
    return any(
        finding.check is CheckType.claim and finding.severity in SERIOUS
        for finding in findings
    )


def _status_of(finding: Finding, facts: ReviewFacts) -> FindingStatus:
    return facts.progress.get(finding.id, FindingProgress()).status


def _still_open(facts: ReviewFacts) -> int:
    def is_open(finding: Finding) -> bool:
        state = _status_of(finding, facts)
        if state is FindingStatus.override_rejected:
            return True
        return state is FindingStatus.open and finding.verdict is not Verdict.PASS

    return sum(is_open(finding) for finding in facts.findings)


def _waiting(facts: ReviewFacts) -> int:
    return sum(
        _status_of(finding, facts) in WAITING_FOR_REVIEWER for finding in facts.findings
    )


def _plural(count: int, noun: str) -> str:
    return f"1 {noun}" if count == 1 else f"{count} {noun}s"


def blocked_by(move: Move, facts: ReviewFacts) -> str | None:
    """Why a move can't happen yet, or None when nothing stands in its way."""
    if move.source is ContentState.ai_review:
        if facts.run_status == "running":
            return "The review is still running"
        if facts.run_status != "done":
            return "The review didn't finish. Start it again."

    leaving_for_review = move.target is ContentState.reviewer_check
    leaving_for_approval = move.target is ContentState.manager_approval
    if leaving_for_review and not facts.covers_latest:
        return "Review the newest version first"

    open_count = _still_open(facts)
    if (leaving_for_review or leaving_for_approval) and open_count:
        return f"{_plural(open_count, 'finding')} still open"
    if leaving_for_approval and (waiting := _waiting(facts)):
        return f"{_plural(waiting, 'decision')} waiting for a reviewer"

    if move.source is ContentState.manager_approval:
        legal = needs_legal(facts.findings)
        if move.target is ContentState.published and legal:
            return "A high-severity claim needs legal sign-off first"
        if move.target is ContentState.legal_signoff and not legal:
            return "Nothing here needs legal sign-off"
    return None


def _may_make(move: Move, user: User, content: Content) -> bool:
    if user.role != move.role.value:
        return False
    return move.role is not Role.creator or content.creator_id == user.id


def available_moves(
    content: Content, user: User, facts: ReviewFacts
) -> list[MoveOption]:
    state = ContentState(content.state)
    options = [
        MoveOption(move.target, move.needs_reason, blocked_by(move, facts))
        for move in MOVES
        if move.source is state and _may_make(move, user, content)
    ]
    if state not in FINISHED and Role(user.role) in REJECTORS:
        options.append(MoveOption(ContentState.rejected, True, None))
    return options


def make_move(
    session: Session,
    *,
    content: Content,
    target: ContentState,
    actor: User,
    facts: ReviewFacts,
    reason: str | None,
    rulebook_version: int | None,
) -> None:
    """Checks and applies a state change. The caller commits."""
    options = {option.to: option for option in available_moves(content, actor, facts)}
    option = options.get(target)
    if option is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can't move this content there."
        )
    if option.blocked_by:
        raise HTTPException(status.HTTP_409_CONFLICT, option.blocked_by)

    reason = (reason or "").strip() or None
    if option.needs_reason and reason is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a reason for this change."
        )
    move_content(
        session,
        content,
        target,
        actor,
        rulebook_version=rulebook_version,
        reason=reason,
    )
