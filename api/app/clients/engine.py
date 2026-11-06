from mocks import engine as mock_engine
from sqlalchemy.orm import Session

from app.clients.flags import use_mock
from app.contracts import ContentSource


def start_review(
    content_version_id: str,
    channel: str,
    rulebook_version: int,
    source: ContentSource | None = None,
) -> str:
    """Starts an AI review and returns its id. The mock ignores `source`."""
    if use_mock("ENGINE"):
        return mock_engine.start_review(channel)["review_id"]
    if source is None:
        raise NotImplementedError("The real engine needs the content to review")

    from app.engine import reviews

    return reviews.start_review(content_version_id, channel, rulebook_version, source)


def review_status(review_id: str, session: Session) -> str:
    """running, done, failed or unknown. Only `done` means every check finished.

    Findings stream in stages, so a move out of ai_review must wait for `done`.
    Mock reviews are complete as soon as they start.
    """
    if use_mock("ENGINE"):
        return "done"

    from app.engine import reviews

    return reviews.review_status(review_id, session)
