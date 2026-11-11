"""The record of a piece of content, and the audit log."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.models import Content, ContentVersion
from app.contracts import ContentState
from app.tenancy import scoped
from app.workflow.models import AuditLog, Decision, Review, ReviewStateLog
from app.workflow.schemas import (
    AuditEntry,
    AuditPage,
    DecisionEntry,
    History,
    PublishedStamp,
    StateEntry,
)

APPROVAL_STATES = (
    ContentState.manager_approval.value,
    ContentState.legal_signoff.value,
    ContentState.published.value,
)


def _stamp(
    session: Session, content: Content, entries: list[ReviewStateLog], names: dict[str, str]
) -> PublishedStamp | None:
    published = [e for e in entries if e.to_state == ContentState.published.value]
    if not published:
        return None
    version = session.scalar(
        scoped(session, ContentVersion, func.max(ContentVersion.version)).where(
            ContentVersion.content_id == content.id
        )
    )
    rulebook = session.scalar(
        scoped(session, Review, Review.rulebook_version)
        .scoped_join(session, ContentVersion, Review.content_version_id == ContentVersion.id)
        .where(ContentVersion.content_id == content.id)
        .order_by(Review.created_at.desc())
        .limit(1)
    )
    approvers = [
        names.get(entry.actor_id, "Unknown")
        for entry in entries
        if entry.to_state in APPROVAL_STATES
    ]
    return PublishedStamp(
        version=version or 0,
        rulebook_version=rulebook or 0,
        approvers=list(dict.fromkeys(approvers)),
        published_at=published[-1].created_at,
    )


def content_history(session: Session, content: Content) -> History:
    entries = list(
        session.scalars(
            scoped(session, ReviewStateLog)
            .where(ReviewStateLog.content_id == content.id)
            .order_by(ReviewStateLog.created_at)
        )
    )
    decisions = session.execute(
        scoped(session, Decision, Decision, ContentVersion.version)
        .scoped_join(session, Review, Decision.review_id == Review.id)
        .scoped_join(session, ContentVersion, Review.content_version_id == ContentVersion.id)
        .where(ContentVersion.content_id == content.id)
        .order_by(Decision.created_at)
    ).all()

    ids = {entry.actor_id for entry in entries}
    ids |= {decision.actor_id for decision, _ in decisions}
    users = session.scalars(scoped(session, User).where(User.id.in_(ids))) if ids else []
    names = {user.id: user.name for user in users}

    return History(
        states=[
            StateEntry(
                from_state=entry.from_state,
                to_state=entry.to_state,
                actor=names.get(entry.actor_id, "Unknown"),
                reason=entry.reason,
                created_at=entry.created_at,
            )
            for entry in entries
        ],
        decisions=[
            DecisionEntry(
                finding_id=decision.finding_id,
                action=decision.action,
                actor=names.get(decision.actor_id, "Unknown"),
                role=decision.role,
                reason=decision.reason,
                version=version,
                created_at=decision.created_at,
            )
            for decision, version in decisions
        ],
        stamp=_stamp(session, content, entries, names),
    )


def audit_page(
    session: Session,
    *,
    action: str | None,
    target_type: str | None,
    role: str | None,
    limit: int,
    offset: int,
) -> AuditPage:
    filters = []
    if action:
        filters.append(AuditLog.action.startswith(action, autoescape=True))
    if target_type:
        filters.append(AuditLog.target_type == target_type)
    if role:
        filters.append(AuditLog.role == role)

    total = session.scalar(scoped(session, AuditLog, func.count()).where(*filters))
    rows = session.execute(
        scoped(session, AuditLog, AuditLog, User.name)
        .scoped_join(session, User, AuditLog.actor_id == User.id, outer=True)
        .where(*filters)
        # The id breaks ties, so a row can't appear on two pages or on neither.
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return AuditPage(
        total=total or 0,
        items=[
            AuditEntry(
                id=entry.id,
                actor=name or "Unknown",
                role=entry.role,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                before=entry.before,
                after=entry.after,
                rulebook_version=entry.rulebook_version,
                created_at=entry.created_at,
            )
            for entry, name in rows
        ],
    )
