"""The CI routes are tested on the same two-org world as the isolation suite."""

import sys
from pathlib import Path

import pytest

# The fixtures live at the repo root, outside api/.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# Imported so pytest finds them here: the same app, database, two orgs and sealed network.
from tests.tenancy.conftest import (  # noqa: F401
    client_for,
    database,
    model_calls,
    real_app,
    sealed,
    world,
)


@pytest.fixture(autouse=True)
def ci_enabled(monkeypatch):
    """The integration ships off. These tests are about it when it is on."""
    monkeypatch.setenv("CI_INTEGRATION_ENABLED", "true")
