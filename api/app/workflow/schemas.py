from pydantic import BaseModel

from app.contracts import ContentState, DecisionAction, FindingStatus


class DecisionIn(BaseModel):
    action: DecisionAction
    reason: str | None = None
    # The creator's wording, for edit_fix. accept_fix uses the engine's offer.
    fix_text: str | None = None


class FixRequest(BaseModel):
    # False returns the stored suggestion, so reopening spends no attempt.
    again: bool = False


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
