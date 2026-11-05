from mocks import engine as mock_engine

from app.clients.flags import use_mock


def start_review(
    content_version_id: str, channel: str, rulebook_version: int
) -> str:
    """Starts an AI review and returns its id."""
    if use_mock("ENGINE"):
        return mock_engine.start_review(channel)["review_id"]
    # Added with USE_MOCK_ENGINE=false in block 4, when the real engine exists.
    raise NotImplementedError("The real engine isn't connected yet")
