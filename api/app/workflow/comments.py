"""Threaded comments on a finding, a span or a whole version."""

import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.models import Content, ContentVersion
from app.workflow.models import Comment
from app.workflow.schemas import CommentIn, CommentOut

MENTION = re.compile(r"(?<![\w.])@([\w.-]+)")


def _names(session: Session, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    users = session.scalars(select(User).where(User.id.in_(ids)))
    return {user.id: user.name for user in users}


def _mentioned(session: Session, body: str) -> list[str]:
    """Matches `@name` against the part of an email before the @."""
    handles = {handle.lower().rstrip(".-") for handle in MENTION.findall(body)}
    if not handles:
        return []
    users = session.scalars(select(User).order_by(User.email))
    return [user.id for user in users if user.email.split("@")[0].lower() in handles]


def list_comments(session: Session, content: Content) -> list[CommentOut]:
    comments = session.scalars(
        select(Comment)
        .join(ContentVersion, Comment.content_version_id == ContentVersion.id)
        .where(ContentVersion.content_id == content.id)
        .order_by(Comment.created_at)
    ).all()
    people = {comment.author_id for comment in comments}
    for comment in comments:
        people.update(comment.mentions)
    names = _names(session, people)
    return [
        CommentOut(
            id=comment.id,
            content_version_id=comment.content_version_id,
            finding_id=comment.finding_id,
            span=comment.span,
            parent_id=comment.parent_id,
            author=names.get(comment.author_id, "Unknown"),
            body=comment.body,
            mentions=[names[m] for m in comment.mentions if m in names],
            created_at=comment.created_at,
        )
        for comment in comments
    ]


def add_comment(session: Session, content: Content, author: User, body: CommentIn) -> None:
    """Stores a comment. The caller commits."""
    text = body.body.strip()
    if not text:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Write something first."
        )

    version = session.get(ContentVersion, body.content_version_id)
    if version is None or version.content_id != content.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")

    parent = session.get(Comment, body.parent_id) if body.parent_id else None
    if body.parent_id and (
        parent is None or parent.content_version_id != version.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")

    session.add(
        Comment(
            content_version_id=version.id,
            finding_id=parent.finding_id if parent else body.finding_id,
            span=body.span.model_dump() if body.span else None,
            parent_id=parent.id if parent else None,
            author_id=author.id,
            body=text,
            mentions=_mentioned(session, text),
        )
    )
