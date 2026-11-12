"""Block 9: the expiry job deletes an expired sandbox and nothing else."""

from __future__ import annotations

from datetime import timedelta

from app import db
from app.auth.defaults import utc_now
from app.auth.models import Organization
from app.auth.orgs import DEMO_ORG_ID, ensure_demo_org
from app.content import storage
from app.tenancy.expiry import delete_expired
from sqlalchemy import select

from tests.tenancy.state import problems, snapshot


def test_an_expired_sandbox_is_deleted_with_its_data_and_files_and_no_other(world):
    with db.get_sessionmaker()() as session:
        ensure_demo_org(session)
        a = session.get(Organization, world.a.org.id)
        a.expires_at = utc_now() - timedelta(days=1)
        # B hasn't expired yet.
        session.get(Organization, world.b.org.id).expires_at = utc_now() + timedelta(
            days=3
        )
        session.commit()
    folder = storage.stored_path(f"{world.a.org.id}/x").parent
    assert folder.is_dir()
    before = snapshot(db.get_engine())

    deleted = delete_expired()

    assert deleted == [world.a.org.id]
    after = snapshot(db.get_engine())
    assert problems(before, after, world.b.owned_ids | {DEMO_ORG_ID}) == []
    assert not folder.exists()
    with db.get_sessionmaker()() as session:
        left = set(session.scalars(select(Organization.id)))
    assert left == {world.b.org.id, DEMO_ORG_ID}
    # Nothing that referred to A is left in any table.
    assert not any(
        world.a.org.id in text
        for (table, _), text in after.items()
        if table != "organizations"
    )


def test_a_standalone_script_sees_every_tenant_table():
    """The expiry job runs on its own. In a fresh process it must still know every table."""
    import subprocess
    import sys
    from pathlib import Path

    from tests.tenancy.inventory import TENANT_TABLES

    code = (
        "from app.tenancy.purge import tenant_models;"
        "print(sorted(m.__tablename__ for m in tenant_models()))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        # The API's own folder, which is where the app is imported from.
        cwd=Path(__file__).resolve().parents[2],
    ).stdout
    assert sorted(eval(out.strip().splitlines()[-1])) == sorted(TENANT_TABLES)
