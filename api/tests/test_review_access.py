"""A review is only as readable as the content it belongs to."""

from __future__ import annotations

import app.admin.models  # noqa: F401
import pytest
from app.auth.models import User
from app.content.models import Content, ContentVersion
from app.db import Base
from app.engine.access import require_review
from app.workflow.models import Review
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def user(user_id, role):
    return User(id=user_id, email=f"{user_id}@x.y", name=user_id, password_hash="x", role=role)


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add_all([
            user("owner", "creator"), user("other", "creator"), user("rev", "reviewer"),
        ])
        s.flush()
        s.add(
            Content(
                id="c", title="t", channel="blog", source="s", data_class="public",
                creator_id="owner",
            )
        )
        s.flush()
        s.add(ContentVersion(id="v", content_id="c", version=1, text="", created_by="owner"))
        s.flush()
        s.add(
            Review(
                id="r", content_version_id="v", engine_review_id="rev-1", channel="blog",
                rulebook_version=1,
            )
        )
        s.commit()
        yield s


def test_the_owner_can_read_their_review(session):
    require_review("rev-1", session.get(User, "owner"), session)


def test_a_reviewer_can_read_any_review(session):
    require_review("rev-1", session.get(User, "rev"), session)


def test_another_creator_gets_a_404(session):
    with pytest.raises(HTTPException) as refused:
        require_review("rev-1", session.get(User, "other"), session)
    assert refused.value.status_code == 404


def test_a_creator_gets_a_404_for_an_unknown_review(session):
    with pytest.raises(HTTPException) as refused:
        require_review("nope", session.get(User, "owner"), session)
    assert refused.value.status_code == 404
