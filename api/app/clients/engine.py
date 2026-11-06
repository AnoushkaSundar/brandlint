from mocks import engine as mock_engine

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
