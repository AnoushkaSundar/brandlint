from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, SessionDep, current_user
from app.auth.models import User
from app.clients import engine as engine_client
from app.content.access import latest_review, readable_content
from app.content.models import Content
from app.contracts import ContentState, Decision, Finding, FindingStatus
from app.workflow import fixes
from app.workflow.decisions import (
    FindingProgress,
    allowed_actions,
    finding_progress,
    list_decisions,
    record_decision,
)
from app.workflow.machine import available_moves, make_move, needs_legal
from app.workflow.models import Review
from app.workflow.schemas import (
    Board,
    DecisionIn,
    FindingStanding,
    MoveOut,
    TransitionIn,
)

router = APIRouter(
    prefix="/workflow", tags=["workflow"], dependencies=[Depends(current_user)]
)


def _findings_for(review: Review | None) -> list[Finding]:
    return engine_client.list_findings(review.engine_review_id) if review else []


def _board(session: Session, content: Content, user: User) -> Board:
    review = latest_review(session, content.id)
    findings = _findings_for(review)
    progress = finding_progress(session, review) if review else {}

    standings = []
    for finding in findings:
        standing = progress.get(finding.id, FindingProgress())
        standings.append(
            FindingStanding(
                id=finding.id,
                status=standing.status,
                fix_text=standing.fix_text,
                allowed=sorted(
                    allowed_actions(finding, standing.status, user, content),
                    key=lambda action: action.value,
                ),
            )
        )
    moves = available_moves(content, user, findings, progress)
    return Board(
        state=ContentState(content.state),
        legal_required=needs_legal(findings),
        findings=standings,
        moves=[
            MoveOut(to=m.to, needs_reason=m.needs_reason, blocked_by=m.blocked_by)
            for m in moves
        ],
    )


@router.get("/content/{content_id}/board", response_model=Board)
def get_board(content_id: str, user: CurrentUser, session: SessionDep) -> Board:
    return _board(session, readable_content(content_id, user, session), user)


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
    review = latest_review(session, content.id)
    finding = next(
        (item for item in _findings_for(review) if item.id == finding_id), None
    )
    if review is None or finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")

    record_decision(
        session,
        content=content,
        review=review,
        finding=finding,
        actor=user,
        action=body.action,
        reason=body.reason,
        fix_text=body.fix_text,
    )
    session.commit()
    return _board(session, content, user)


@router.post("/content/{content_id}/transitions", response_model=Board)
def transition(
    content_id: str, body: TransitionIn, user: CurrentUser, session: SessionDep
) -> Board:
    content = readable_content(content_id, user, session)
    review = latest_review(session, content.id)
    findings = _findings_for(review)
    progress = finding_progress(session, review) if review else {}

    make_move(
        session,
        content=content,
        target=body.to,
        actor=user,
        findings=findings,
        progress=progress,
        reason=body.reason,
        rulebook_version=review.rulebook_version if review else None,
    )
    fixed = any(
        standing.status in (FindingStatus.fix_accepted, FindingStatus.fix_edited)
        for standing in progress.values()
    )
    if review and fixed and body.to is ContentState.reviewer_check:
        chunks = engine_client.list_chunks(review.engine_review_id)
        fixes.save_fixed_version(
            session, content, fixes.text_with_fixes(chunks, findings, progress), user
        )
    session.commit()
    return _board(session, content, user)


@router.get("/decisions", response_model=list[Decision])
def get_decisions(session: SessionDep, since: datetime | None = None) -> list:
    return list(list_decisions(session, since))
