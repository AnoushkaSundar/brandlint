"""The rulebook a review runs against. The engine calls these functions directly."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.admin.models import Rule as RuleRow
from app.contracts import Rule, RuleStatus
from app.tenancy import scoped


class RulebookNotFound(LookupError):
    """No approved rules exist at the version asked for."""


def current_rulebook_version(session: Session | None = None) -> int:
    """The version a new review pins: the newest approved rule version.

    Approving rules creates rows at a higher version, so approval bumps this.
    """
    if session is None:
        return 1
    newest = session.scalar(
        scoped(session, RuleRow, func.max(RuleRow.version)).where(
            RuleRow.status == RuleStatus.approved.value
        )
    )
    return newest or 1


def rulebook_at(session: Session, version: int | None = None) -> list[Rule]:
    """Returns the approved rules in force at a version, by default the current one.

    A rule's row version is the rulebook version that introduced it, so each rule is
    read from its newest decided row at or before `version`. Drafts are undecided, and
    retiring or superseding a rule ends it.

    Raises RulebookNotFound rather than returning nothing, because a review against an
    empty rulebook would pass everything.
    """
    current = current_rulebook_version(session)
    pinned = current if version is None else version
    if pinned > current:
        raise RulebookNotFound(f"Rulebook version {pinned} doesn't exist yet")

    rows = session.scalars(
        scoped(session, RuleRow)
        .where(RuleRow.version <= pinned, RuleRow.status != RuleStatus.draft.value)
        .order_by(RuleRow.id, RuleRow.version)
    ).all()
    newest = {row.id: row for row in rows}
    superseded = {row.supersedes for row in rows if row.supersedes != row.id}

    rules = [
        Rule.model_validate(row, from_attributes=True)
        for row in newest.values()
        if row.status == RuleStatus.approved.value and row.id not in superseded
    ]
    if not rules:
        raise RulebookNotFound(f"No approved rules at rulebook version {pinned}")
    return rules
