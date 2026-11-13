"""Fixtures for the isolation tests.

The app under test is the real one: every USE_MOCK_* flag is off, so the real engine,
gateway, memory and governance routes are mounted, and requests reach them through the
app's own session factory. Nothing can reach a model or the network: that would cost
money (LiteLLM listens on localhost:4000 on a developer machine) and prove nothing.
"""

from __future__ import annotations

import json
import re
import socket

import pytest
from app import db
from app.auth.security import SESSION_COOKIE
from app.db import Base
from app.engine import reviews
from app.gateway import llm, masking
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from tests.tenancy import inventory
from tests.tenancy.routes import real_services
from tests.tenancy.world import Person, World, build_world


class Blocked(AssertionError):
    """Something in an isolation test tried to reach a model or the network."""


def _is_a_fake_server(host, port) -> bool:
    """Only the fake GitHub and fake BrandLint of the CI tests, on the loopback address."""
    try:
        from integrations.fixtures import ALLOWED_PORTS
    except ImportError:  # the repo root isn't on the path, so there are no fakes
        return False

    return host in ("127.0.0.1", "localhost") and port in ALLOWED_PORTS


def _blocked(*args, **kwargs):
    raise Blocked("An isolation test tried to reach the network")


def stand_in_model(model_calls: list[str]):
    """Answers the ingest prompts with rules read from the guideline, and refuses the rest.

    Ingest needs an answer for its drafts to exist and be visible. Every other call is
    refused, and what it would have sent is kept so a test can look for another org's text.
    """

    def reply(content: str) -> dict:
        return {"model": "stand-in", "choices": [{"message": {"content": content}}]}

    def model(body: dict) -> dict:
        model_calls.append(str(body))
        system = body["messages"][0]["content"]
        material = body["messages"][-1]["content"]
        if "atomic rules" in system:
            rules = [
                {
                    "type": "judgment",
                    "text": line.split(None, 1)[1],
                    "clause_ref": f"§{line.split()[0]}",
                    "severity": "low",
                    "channel_scope": [],
                }
                for line in material.splitlines()
                if re.match(r"\d+\.\d+\s+\S", line)
            ]
            return reply(json.dumps({"rules": rules, "conflicts": []}))
        if "contradictions" in system:
            return reply(json.dumps({"conflicts": []}))
        raise Blocked("An isolation test tried to call a model")

    return model


@pytest.fixture()
def model_calls() -> list[str]:
    """What each blocked call to a model would have sent, so a test can look for leaked text."""
    return []


@pytest.fixture(autouse=True)
def sealed(monkeypatch, tmp_path, model_calls):
    monkeypatch.setenv("JWT_SECRET", "a-test-only-secret-that-is-long-enough-for-hs256")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    # The CI routes ship off. The isolation suite covers them as if they were on.
    monkeypatch.setenv("CI_INTEGRATION_ENABLED", "true")

    monkeypatch.setattr(llm, "_chat_completion", stand_in_model(model_calls))
    # Presidio is a separate service. Nothing it would find matters to isolation.
    monkeypatch.setattr(masking, "analyze", lambda text: [])
    real_getaddrinfo, real_create_connection = socket.getaddrinfo, socket.create_connection

    def getaddrinfo(host, port, *args, **kwargs):
        if _is_a_fake_server(host, port):
            return real_getaddrinfo(host, port, *args, **kwargs)
        return _blocked()

    def create_connection(address, *args, **kwargs):
        if _is_a_fake_server(*address[:2]):
            return real_create_connection(address, *args, **kwargs)
        return _blocked()

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", create_connection)


@pytest.fixture(scope="module")
def real_app():
    """The whole app with real services. The flags are put back afterwards."""
    with real_services():
        yield create_app()


@pytest.fixture()
def database(tmp_path):
    """A fresh SQLite file that the app's own session factory points at."""
    inventory.model_tables()
    url = f"sqlite:///{tmp_path / 'tenancy.db'}?check_same_thread=false&timeout=30"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db, "DATABASE_URL", url)
        db.get_engine.cache_clear()
        db.get_sessionmaker.cache_clear()
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()
            db.get_engine().dispose()
    db.get_engine.cache_clear()
    db.get_sessionmaker.cache_clear()


@pytest.fixture()
def world(database) -> World:
    """Two orgs, each with an admin, a reviewer and a creator, and data in every table."""
    reviews._runs.clear()
    with db.get_sessionmaker()() as session:
        built = build_world(session)
    reviews._runs[built.a.run.review_id] = built.a.run
    reviews._runs[built.b.run.review_id] = built.b.run
    yield built
    reviews._runs.clear()


@pytest.fixture()
def client_for(real_app):
    """A client signed in as the given person."""

    def build(person: Person) -> TestClient:
        client = TestClient(real_app, raise_server_exceptions=False)
        client.cookies.set(SESSION_COOKIE, person.token)
        return client

    return build
