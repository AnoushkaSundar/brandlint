from pydantic import BaseModel

from app.contracts import ContentState, DecisionAction, FindingStatus


class DecisionIn(BaseModel):
    action: DecisionAction
    reason: str | None = None
    # The accepted or edited wording, for accept_fix and edit_fix.
    fix_text: str | None = None


class TransitionIn(BaseModel):
    to: ContentState
    reason: str | None = None


class FindingStanding(BaseModel):
    id: str
    status: FindingStatus
    fix_text: str | None
    # The same list the server enforces, so the UI can't offer what would be refused.
    allowed: list[DecisionAction]


class MoveOut(BaseModel):
    to: ContentState
    needs_reason: bool
    blocked_by: str | None


class Board(BaseModel):
    state: ContentState
    legal_required: bool
    findings: list[FindingStanding]
    moves: list[MoveOut]
