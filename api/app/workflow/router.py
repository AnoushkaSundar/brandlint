from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    CurrentUser,
    SessionDep,
    current_user,
    require_roles,
)
from app.auth.models import User
from app.clients import engine as engine_client
from app.content.access import latest_review, readable_content
from app.content.models import Content, ContentVersion
from app.contracts import (
    ContentState,
    Decision,
    DecisionAction,
    Finding,
    FixSuggestion,
    Role,
)
from app.workflow import fixes
from app.workflow.decisions import (
    FindingProgress,
    allowed_actions,
    finding_progress,
    list_decisions,
    record_decision,
    refused_overrides,
)
from app.workflow.machine import ReviewFacts, available_moves, make_move, needs_legal
from app.workflow.models import Review
from app.workflow.schemas import (
    Board,
    DecisionIn,
    FindingStanding,
    FixRequest,
    MoveOut,
    TransitionIn,
)

router = APIRouter(
    prefix="/workflow", tags=["workflow"], dependencies=[Depends(current_user)]
)


def _covers_latest(session: Session, content: Content, review: Review) -> bool:
    newest = session.scalar(
        select(ContentVersion.id)
        .where(ContentVersion.content_id == content.id)
        .order_by(ContentVersion.version.desc())
        .limit(1)
    )
    return newest == review.content_version_id


def _facts(session: Session, content: Content, review: Review | None) -> ReviewFacts:
    if review is None:
        return ReviewFacts()
    return ReviewFacts(
        findings=engine_client.list_findings(review.engine_review_id),
        progress=finding_progress(session, review),
        run_status=engine_client.review_status(review.engine_review_id, session),
        covers_latest=_covers_latest(session, content, review),
    )


def _board(session: Session, content: Content, user: User) -> Board:
    facts = _facts(session, content, latest_review(session, content.id))
    refused = refused_overrides(session, content.id)

    standings = []
    for finding in facts.findings:
        standing = facts.progress.get(finding.id, FindingProgress())
        standings.append(
            FindingStanding(
                id=finding.id,
                status=standing.status,
                fix_text=standing.fix_text,
                allowed=sorted(
                    allowed_actions(finding, standing.status, user, content, refused),
                    key=lambda action: action.value,
                ),
            )
        )
    return Board(
        state=ContentState(content.state),
        legal_required=needs_legal(facts.findings),
        findings=standings,
        moves=[
            MoveOut(to=m.to, needs_reason=m.needs_reason, blocked_by=m.blocked_by)
            for m in available_moves(content, user, facts)
        ],
    )


def _finding_in(
    session: Session, content: Content, finding_id: str
) -> tuple[Review, Finding, list[Finding]]:
    review = latest_review(session, content.id)
    findings = (
        engine_client.list_findings(review.engine_review_id) if review else []
    )
    finding = next((item for item in findings if item.id == finding_id), None)
    if review is None or finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return review, finding, findings


@router.get("/content/{content_id}/board", response_model=Board)
def get_board(content_id: str, user: CurrentUser, session: SessionDep) -> Board:
    return _board(session, readable_content(content_id, user, session), user)


@router.post(
    "/content/{content_id}/findings/{finding_id}/fix",
    response_model=FixSuggestion,
)
def request_fix(
    content_id: str,
    finding_id: str,
    body: FixRequest,
    user: CurrentUser,
    session: SessionDep,
) -> FixSuggestion:
    content = readable_content(content_id, user, session)
    review, finding, _ = _finding_in(session, content, finding_id)
    standing = finding_progress(session, review).get(finding.id, FindingProgress())
    if DecisionAction.accept_fix not in allowed_actions(
        finding, standing.status, user, content
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can't ask for a fix on this finding."
        )
    suggestion = fixes.offer_fix(session, review, finding.id, again=body.again)
    session.commit()
    return suggestion


@router.post(
    "/content/{content_id}/findings/{finding_id}/decisions",
    response_model=Board,
    status_code=status.HTTP_201_CREATED,
)
def decide(
    content_id: str,
    finding_id: str,
    body: DecisionIn,
    user: CurrentUser,
    session: SessionDep,
) -> Board:
    content = readable_content(content_id, user, session)
    review, finding, findings = _finding_in(session, content, finding_id)
    record_decision(
        session,
        content=content,
        review=review,
        finding=finding,
        findings=findings,
        actor=user,
        action=body.action,
        reason=body.reason,
        fix_text=body.fix_text,
    )
    session.commit()
    return _board(session, content, user)


def _fixed_text(review: Review, facts: ReviewFacts) -> str | None:
    """The text with every approved fix in place, or None when there are no fixes."""
    if not any(item.fix_text for item in facts.progress.values()):
        return None
    chunks = engine_client.list_chunks(review.engine_review_id)
    try:
        return fixes.text_with_fixes(chunks, facts.findings, facts.progress)
    except fixes.FixesOverlap:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Two saved fixes overlap. Send this back."
        ) from None


@router.post("/content/{content_id}/transitions", response_model=Board)
def transition(
    content_id: str, body: TransitionIn, user: CurrentUser, session: SessionDep
) -> Board:
    content = readable_content(content_id, user, session)
    review = latest_review(session, content.id)
    facts = _facts(session, content, review)

    # Sign-off comes first, so a rejected edit never reaches a version.
    approving = body.to is ContentState.manager_approval
    fixed_text = _fixed_text(review, facts) if review and approving else None
    make_move(
        session,
        content=content,
        target=body.to,
        actor=user,
        facts=facts,
        reason=body.reason,
        rulebook_version=review.rulebook_version if review else None,
    )
    if fixed_text is not None:
        fixes.save_fixed_version(session, content, fixed_text, user)
    session.commit()
    return _board(session, content, user)


@router.get(
    "/decisions",
    response_model=list[Decision],
    dependencies=[
        Depends(require_roles(Role.reviewer, Role.manager, Role.legal, Role.admin))
    ],
)
def get_decisions(session: SessionDep, since: datetime | None = None) -> list:
    return list(list_decisions(session, since))
