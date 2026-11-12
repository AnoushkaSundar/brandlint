"""Turns committed decisions, state changes and comments into live events.

A SQLAlchemy hook collects the rows a request adds, and publishes them only after the
transaction commits, so nobody is told about something that was rolled back. It reads
nothing the request didn't already write, and it never changes the workflow: a failure
here is logged and swallowed, and can't fail a decision.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.auth.models import User
from app.collab.hub import Person, hub
from app.content.models import ContentVersion
from app.tenancy import bind_org, bound_org
from app.workflow.models import Comment, Decision, Review, ReviewStateLog

logger = logging.getLogger(__name__)
PENDING = "collab_pending"


def _snapshot(row: Any) -> tuple[str, dict[str, Any]] | None:
    """What an event needs from a new row, taken at flush while its values are set."""
    if isinstance(row, Decision):
        return "decision", {
            "id": row.id, "review_id": row.review_id, "finding_id": row.finding_id,
            "actor_id": row.actor_id, "role": row.role, "action": row.action,
            "status": row.status, "reason": row.reason,
        }
    if isinstance(row, ReviewStateLog):
        return "state", {
            "id": row.id, "content_id": row.content_id, "actor_id": row.actor_id,
            "from": row.from_state, "to": row.to_state, "reason": row.reason,
        }
    if isinstance(row, Comment):
        return "comment", {
            "id": row.id, "content_version_id": row.content_version_id,
            "finding_id": row.finding_id, "actor_id": row.author_id,
        }
    return None


@event.listens_for(Session, "after_flush")
def collect(session: Session, flush_context) -> None:
    for row in session.new:
        found = _snapshot(row)
        if found is not None:
            session.info.setdefault(PENDING, []).append(found)


@event.listens_for(Session, "after_soft_rollback")
def forget(session: Session, previous_transaction) -> None:
    # A rolled-back request published nothing and must not leak into the next one.
    session.info.pop(PENDING, None)


@event.listens_for(Session, "after_commit")
def announce(session: Session) -> None:
    pending = session.info.pop(PENDING, None)
    if not pending:
        return
    try:
        _publish(session, pending)
    except Exception:
        logger.warning("could not publish live events", exc_info=True)


def _publish(session: Session, pending: list[tuple[str, dict[str, Any]]]) -> None:
    with Session(session.get_bind()) as lookup:
        org = bound_org(session)
        if org is not None:
            bind_org(lookup, org)
        people: dict[str, Person] = {}

        def person(user_id: str, role: str | None = None) -> Person:
            if user_id not in people:
                # unscoped-ok: looked up by id, in the committing session's own org
                user = lookup.get(User, user_id)
                people[user_id] = Person(
                    user_id, user.name if user else "Someone", role or (user.role if user else "")
                )
            return people[user_id]

        def content_of_review(review_id: str) -> str | None:
            # unscoped-ok: looked up by id, in the committing session's own org
            review = lookup.get(Review, review_id)
            if review is None:
                return None
            # unscoped-ok: looked up by id, in the committing session's own org
            version = lookup.get(ContentVersion, review.content_version_id)
            return version.content_id if version else None

        for kind, row in pending:
            if kind == "decision":
                content_id = content_of_review(row["review_id"])
                if content_id is None:
                    continue
                actor = person(row["actor_id"], row["role"])
                hub.publish(content_id, "decision", {
                    "id": row["id"], "finding_id": row["finding_id"], "actor": actor.as_dict(),
                    "action": row["action"], "status": row["status"], "reason": row["reason"],
                })
                clash = hub.note_decision(
                    content_id, row["finding_id"], actor, row["action"], row["status"]
                )
                if clash is not None:
                    hub.publish(content_id, "conflict", clash)
            elif kind == "state":
                hub.publish(row["content_id"], "state", {
                    "id": row["id"], "from": row["from"], "to": row["to"],
                    "actor": person(row["actor_id"]).as_dict(), "reason": row["reason"],
                })
            elif kind == "comment":
                # unscoped-ok: looked up by id, in the committing session's own org
                version = lookup.get(ContentVersion, row["content_version_id"])
                if version is None:
                    continue
                hub.publish(version.content_id, "comment", {
                    "id": row["id"], "finding_id": row["finding_id"],
                    "actor": person(row["actor_id"]).as_dict(),
                })
