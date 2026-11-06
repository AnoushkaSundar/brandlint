from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.models import Content
from app.contracts import ContentState
from app.workflow.models import AuditLog, ReviewStateLog


def move_content(
    session: Session,
    content: Content,
    to_state: ContentState,
    actor: User,
    *,
    rulebook_version: int | None = None,
    reason: str | None = None,
) -> None:
    """Moves content to a new state, and records it in the state log and audit log.

    The caller commits. The rules for which moves are allowed land in block 5.
    """
    from_state = content.state
    if from_state == to_state.value:
        return

    content.state = to_state.value
    session.add(
        ReviewStateLog(
            content_id=content.id,
            from_state=from_state,
            to_state=to_state.value,
            actor_id=actor.id,
            reason=reason,
        )
    )
    session.add(
        AuditLog(
            actor_id=actor.id,
            role=actor.role,
            action="state_change",
            target_type="content",
            target_id=content.id,
            before={"state": from_state},
            after={"state": to_state.value},
            rulebook_version=rulebook_version,
        )
    )
