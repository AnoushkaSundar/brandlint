from mocks import engine as mock_engine
from sqlalchemy.orm import Session

from app.clients.flags import use_mock
from app.contracts import Chunk, ContentSource, Finding, FixSuggestion
from app.db import get_sessionmaker


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


def list_findings(engine_review_id: str) -> list[Finding]:
    """Every finding in a review. Overrides read severity and verdict from here.

    Empty for a review the engine doesn't know, so check `review_status` first:
    only `done` means this list is complete.
    """
    if use_mock("ENGINE"):
        found = mock_engine.review_findings(engine_review_id)
        return [Finding.model_validate(finding) for finding in found]

    from app.engine import reviews

    with get_sessionmaker()() as session:
        return reviews.list_findings(engine_review_id, session)


def list_chunks(engine_review_id: str) -> list[Chunk]:
    """The parsed chunks of a review. Accepted fixes are applied to these."""
    if use_mock("ENGINE"):
        return [Chunk.model_validate(c) for c in mock_engine.list_chunks(engine_review_id)]

    from app.engine import reviews

    with get_sessionmaker()() as session:
        return reviews.list_chunks(engine_review_id, session)


def review_status(review_id: str, session: Session) -> str:
    """running, done, failed or unknown. Only `done` means every check finished.

    Findings stream in stages, so a move out of ai_review must wait for `done`.
    Mock reviews are complete as soon as they start.
    """
    if use_mock("ENGINE"):
        return "done"

    from app.engine import reviews

    return reviews.review_status(review_id, session)


def request_fix(finding_id: str, attempt: int) -> FixSuggestion:
    """Asks the engine for a fix. The workflow stores it and enforces the two attempts."""
    if use_mock("ENGINE"):
        return FixSuggestion.model_validate(mock_engine.suggest_fix(finding_id, attempt))
    # The real fixer lands in block 6.
    raise NotImplementedError("The real engine isn't connected yet")
