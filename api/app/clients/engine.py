from mocks import engine as mock_engine
from sqlalchemy.orm import Session

from app.clients.flags import use_mock
from app.contracts import Chunk, ContentSource, Finding, FixSuggestion


def start_review(
    content_version_id: str,
    channel: str,
    rulebook_version: int,
    source: ContentSource | None = None,
) -> str:
    """Starts an AI review and returns its id. The mock ignores `source`."""
    if use_mock("ENGINE"):
        return mock_engine.start_review(channel)["review_id"]
    # Added with USE_MOCK_ENGINE=false in block 4, when the real engine exists.
    raise NotImplementedError("The real engine isn't connected yet")


def list_findings(engine_review_id: str) -> list[Finding]:
    """Every finding in a review. Overrides read severity and verdict from here."""
    if use_mock("ENGINE"):
        found = mock_engine.review_findings(engine_review_id)
        return [Finding.model_validate(finding) for finding in found]
    raise NotImplementedError("The real engine isn't connected yet")


def list_chunks(engine_review_id: str) -> list[Chunk]:
    """The parsed chunks of a review. Accepted fixes are applied to these."""
    if use_mock("ENGINE"):
        return [Chunk.model_validate(c) for c in mock_engine.list_chunks(engine_review_id)]
    raise NotImplementedError("The real engine isn't connected yet")


def review_status(review_id: str, session: Session) -> str:
    """running, done, failed or unknown. Only `done` means every check finished."""
    if use_mock("ENGINE"):
        return "done"
    raise NotImplementedError("The real engine isn't connected yet")


def request_fix(finding_id: str, attempt: int) -> FixSuggestion:
    """Asks the engine for a fix. The workflow stores it and enforces the two attempts."""
    if use_mock("ENGINE"):
        return FixSuggestion.model_validate(mock_engine.suggest_fix(finding_id, attempt))
    raise NotImplementedError("The real engine isn't connected yet")
