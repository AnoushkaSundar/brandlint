"""The guideline-gap log: uncited findings go here and never reach the creator."""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.admin.models import Gap as GapRow
from app.contracts import Gap
from app.tenancy import scoped


def save_gaps(session: Session, gaps: Iterable[Gap]) -> int:
    """Adds gaps to the log and returns how many were new. The caller commits.

    Gap ids are stable, so running a review again repeats them. A gap already in the
    log keeps its original time.
    """
    incoming = {gap.id: gap for gap in gaps}
    known = set(session.scalars(scoped(session, GapRow, GapRow.id).where(GapRow.id.in_(list(incoming)))))
    new = [gap for gap_id, gap in incoming.items() if gap_id not in known]
    session.add_all(
        GapRow(
            id=gap.id,
            review_id=gap.review_id,
            check=gap.check.value,
            text=gap.text,
            explanation=gap.explanation,
            created_at=gap.created_at,
        )
        for gap in new
    )
    return len(new)
