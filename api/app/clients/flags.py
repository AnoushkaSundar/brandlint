import os


def use_mock(service: str) -> bool:
    """Reads USE_MOCK_ENGINE, USE_MOCK_GATEWAY or USE_MOCK_MEMORY. Mocks are the default."""
    return os.environ.get(f"USE_MOCK_{service}", "true").lower() == "true"
