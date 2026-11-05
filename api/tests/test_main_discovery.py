"""API skeleton: router auto-discovery and the app wiring."""

from __future__ import annotations

from app.main import app, discover_routers
from fastapi import APIRouter
from fastapi.testclient import TestClient


def test_health_endpoint():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_discovery_returns_apirouters():
    routers = discover_routers()
    assert routers, "no routers discovered"
    assert all(isinstance(r, APIRouter) for r in routers)


def test_engine_router_is_autodiscovered_and_served():
    # Proves a package's router.py is picked up without touching main.py.
    client = TestClient(app)
    resp = client.get("/engine/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "engine"
