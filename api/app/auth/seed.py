"""Creates the demo users: python -m app.auth.seed

Safe to run twice. Set SEED_PASSWORD to choose the password they all share.
"""

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.orgs import ensure_demo_org
from app.auth.security import hash_password
from app.contracts import Role
from app.db import get_sessionmaker

DEFAULT_PASSWORD = "brandlint-demo"

# One user per role, plus an agency creator and an in-house creator.
SEED_USERS = [
    ("creator@tarnhollow.example", "Sam Okafor", Role.creator, None),
    ("reviewer@tarnhollow.example", "Lena Fischer", Role.reviewer, None),
    ("manager@tarnhollow.example", "Marcus Bell", Role.manager, None),
    ("legal@tarnhollow.example", "Aisha Rahman", Role.legal, None),
    ("admin@tarnhollow.example", "Noor Haddad", Role.admin, None),
    ("agency@tarnhollow.example", "Priya Nair", Role.creator, "agency"),
    ("inhouse@tarnhollow.example", "Tom Reid", Role.creator, "in-house"),
]


def seed_users(session: Session, password: str = DEFAULT_PASSWORD) -> int:
    """Adds any missing demo users to the demo org and returns how many were created."""
    org = ensure_demo_org(session)
    existing = set(session.scalars(select(User.email)))
    missing = [row for row in SEED_USERS if row[0] not in existing]
    password_hash = hash_password(password)
    session.add_all(
        User(
            email=email,
            name=name,
            role=role.value,
            tag=tag,
            password_hash=password_hash,
            org_id=org.id,
        )
        for email, name, role, tag in missing
    )
    session.commit()
    return len(missing)


def main() -> None:
    password = os.environ.get("SEED_PASSWORD", DEFAULT_PASSWORD)
    with get_sessionmaker()() as session:
        created = seed_users(session, password)
    print(f"Created {created} users, {len(SEED_USERS)} expected in total.")


if __name__ == "__main__":
    main()
