"""Block 1: a machine can authenticate safely, and only for CI."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from app import db
from app.auth.defaults import utc_now
from app.auth.models import Organization
from app.ci import auth as ci_auth
from app.ci.models import ServiceToken
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create(client, **body):
    return client.post("/ci/tokens", json={"name": "GitHub Action", **body})


@pytest.fixture()
def anonymous(database, real_app):
    return TestClient(real_app, raise_server_exceptions=False)


def test_a_token_is_shown_once_and_only_its_hash_is_stored(world, client_for, database):
    admin = client_for(world.a.admin)
    made = create(admin)
    assert made.status_code == 201
    token = made.json()["token"]
    assert token.startswith("bl_") and len(token) > 40

    listed = admin.get("/ci/tokens").json()
    entry = next(row for row in listed if row["id"] == made.json()["id"])
    assert entry["prefix"] == token[:8]
    assert "token" not in entry and "token_hash" not in entry

    with database.connect() as connection:
        stored = str(connection.execute(text("select * from service_tokens")).all())
    assert token not in stored
    assert hashlib.sha256(token.encode()).hexdigest() in stored


def test_the_token_works_on_ci_routes_and_nowhere_else(world, client_for, anonymous):
    token = create(client_for(world.a.admin)).json()["token"]
    assert anonymous.get("/ci/whoami", headers=bearer(token)).json()["kind"] == "token"
    for path in ("/content", "/admin/rulebook", "/workflow/queue", "/auth/me", "/ci/tokens"):
        assert anonymous.get(path, headers=bearer(token)).status_code == 401, path


def test_a_signed_in_person_can_use_the_ci_routes_too(world, client_for):
    for person in (world.a.admin, world.a.creator, world.a.reviewer):
        assert client_for(person).get("/ci/whoami").json()["kind"] == "user"


def test_a_wrong_or_malformed_token_is_refused(anonymous):
    assert anonymous.get("/ci/whoami", headers=bearer("bl_not-a-real-token")).status_code == 401
    assert anonymous.get("/ci/whoami", headers=bearer("not-a-token")).status_code == 401
    assert anonymous.get("/ci/whoami").status_code == 401


def test_revoking_takes_effect_on_the_next_request(world, client_for, anonymous):
    admin = client_for(world.a.admin)
    made = create(admin).json()
    assert anonymous.get("/ci/whoami", headers=bearer(made["token"])).status_code == 200
    assert admin.delete(f"/ci/tokens/{made['id']}").status_code == 204
    assert anonymous.get("/ci/whoami", headers=bearer(made["token"])).status_code == 401
    revoked = next(r for r in admin.get("/ci/tokens").json() if r["id"] == made["id"])
    assert revoked["revoked_at"] is not None


def test_an_expired_token_is_refused(world, client_for, anonymous):
    made = create(client_for(world.a.admin), expires_in_days=1).json()
    assert anonymous.get("/ci/whoami", headers=bearer(made["token"])).status_code == 200
    with db.get_sessionmaker()() as session:
        session.execute(
            update(ServiceToken)
            .where(ServiceToken.id == made["id"])
            .values(expires_at=utc_now() - timedelta(minutes=1))
        )
        session.commit()
    assert anonymous.get("/ci/whoami", headers=bearer(made["token"])).status_code == 401


def test_a_suspended_workspaces_token_is_refused_at_once(world, client_for, anonymous):
    token = create(client_for(world.a.admin)).json()["token"]
    with db.get_sessionmaker()() as session:
        session.get(Organization, world.a.org.id).status = "suspended"
        session.commit()
    assert anonymous.get("/ci/whoami", headers=bearer(token)).status_code == 403


def test_the_token_is_compared_in_constant_time(world, client_for, anonymous, monkeypatch):
    token = create(client_for(world.a.admin)).json()["token"]
    seen = []
    real = ci_auth.hmac.compare_digest
    monkeypatch.setattr(
        ci_auth.hmac, "compare_digest", lambda a, b: seen.append(1) or real(a, b)
    )
    assert anonymous.get("/ci/whoami", headers=bearer(token)).status_code == 200
    assert seen


def test_last_used_is_recorded_at_most_once_a_minute(world, client_for, anonymous):
    made = create(client_for(world.a.admin)).json()

    def last_used():
        with db.get_sessionmaker()() as session:
            return session.scalar(
                select(ServiceToken.last_used_at).where(ServiceToken.id == made["id"])
            )

    assert last_used() is None
    anonymous.get("/ci/whoami", headers=bearer(made["token"]))
    first = last_used()
    assert first is not None
    anonymous.get("/ci/whoami", headers=bearer(made["token"]))
    assert last_used() == first  # within a minute: not touched again

    stale = utc_now() - timedelta(minutes=2)
    with db.get_sessionmaker()() as session:
        session.execute(
            update(ServiceToken).where(ServiceToken.id == made["id"]).values(last_used_at=stale)
        )
        session.commit()
    anonymous.get("/ci/whoami", headers=bearer(made["token"]))
    refreshed = last_used()
    assert refreshed is not None and refreshed.replace(tzinfo=None) > stale.replace(tzinfo=None)


def test_an_admin_manages_only_their_own_workspaces_tokens(world, client_for):
    a, b = client_for(world.a.admin), client_for(world.b.admin)
    made = create(a).json()
    assert made["id"] not in {row["id"] for row in b.get("/ci/tokens").json()}
    assert b.delete(f"/ci/tokens/{made['id']}").status_code == 404
    assert client_for(world.a.creator).post("/ci/tokens", json={"name": "x"}).status_code == 403
    assert client_for(world.a.reviewer).get("/ci/tokens").status_code == 403


def test_creating_and_revoking_a_token_is_recorded_in_the_audit_log(world, client_for):
    admin = client_for(world.a.admin)
    made = create(admin).json()
    admin.delete(f"/ci/tokens/{made['id']}")
    with db.get_sessionmaker()() as session:
        actions = {
            row[0]
            for row in session.execute(
                text("select action from audit_log where target_id = :t"), {"t": made["id"]}
            )
        }
    assert actions == {"ci_token_created", "ci_token_revoked"}


def test_the_ci_routes_are_off_until_switched_on(world, client_for, anonymous, monkeypatch):
    token = create(client_for(world.a.admin)).json()["token"]
    monkeypatch.delenv("CI_INTEGRATION_ENABLED")
    assert anonymous.get("/ci/whoami", headers=bearer(token)).status_code == 404
    assert client_for(world.a.admin).get("/ci/tokens").status_code == 404
