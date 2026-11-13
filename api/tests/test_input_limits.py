"""Size and shape limits on what a person can type, found by throwing hostile input at the live API.

A 200 KB override reason was saved as sent, which would let one request put a megabyte into the
audit log, and a whitespace-only comment was accepted. Each is refused with a 422 now.
"""

import pytest
from app.workflow.schemas import CommentIn, DecisionIn, TransitionIn
from pydantic import ValidationError


def test_a_reasonable_reason_is_accepted():
    assert DecisionIn(action="override", reason="A direct customer quote.").reason


def test_an_enormous_reason_is_refused():
    with pytest.raises(ValidationError):
        DecisionIn(action="override", reason="r" * 2001)


def test_an_enormous_edited_fix_is_refused():
    with pytest.raises(ValidationError):
        DecisionIn(action="edit_fix", fix_text="f" * 10_001)


def test_an_enormous_transition_reason_is_refused():
    with pytest.raises(ValidationError):
        TransitionIn(to="resolving", reason="r" * 2001)


@pytest.mark.parametrize("body", ["", "   ", "\n\t "])
def test_a_blank_comment_is_refused(body):
    with pytest.raises(ValidationError):
        CommentIn(body=body, content_version_id="v1")


def test_an_enormous_comment_is_refused():
    with pytest.raises(ValidationError):
        CommentIn(body="c" * 5001, content_version_id="v1")


def test_a_comment_is_trimmed_not_rejected():
    assert CommentIn(body="  Looks fine.  ", content_version_id="v1").body == "Looks fine."
