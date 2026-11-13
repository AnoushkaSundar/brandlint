"""Fixtures for the CI/CD integration tests (docs/ci-integration.md)."""

# Ports the fake servers listen on. The isolation tests seal the network, and let exactly
# these through, so the fakes can be reached while a model or LiteLLM still can't be.
ALLOWED_PORTS: set[int] = set()
