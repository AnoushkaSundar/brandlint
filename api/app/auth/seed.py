"""Creates the demo users: python -m app.auth.seed

Safe to run twice. Set SEED_PASSWORD to choose the password they all share.
"""

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.database import session_factory
from app.auth.models import User
from app.auth.roles import Role
from app.auth.security import hash_password

DEFAULT_PASSWORD = "brandlint-demo"

# One user per role, plus an agency creator and an in-house creator.
SEED_USERS = [
    ("creator@tarnhollow.example", "Sam Okafor", Role.CREATOR, None),
    ("reviewer@tarnhollow.example", "Lena Fischer", Role.REVIEWER, None),
    ("manager@tarnhollow.example", "Marcus Bell", Role.MANAGER, None),
    ("legal@tarnhollow.example", "Aisha Rahman", Role.LEGAL, None),
    ("admin@tarnhollow.example", "Noor Haddad", Role.ADMIN, None),
    ("agency@tarnhollow.example", "Priya Nair", Role.CREATOR, "agency"),
    ("inhouse@tarnhollow.example", "Tom Reid", Role.CREATOR, "in-house"),
]


def seed_users(session: Session, password: str = DEFAULT_PASSWORD) -> int:
    """Adds any missing demo users and returns how many were created."""
    existing = set(session.scalars(select(User.email)))
    missing = [row for row in SEED_USERS if row[0] not in existing]
    password_hash = hash_password(password)
    session.add_all(
        User(
            email=email,
            name=name,
            role=role,
            tag=tag,
            password_hash=password_hash,
        )
        for email, name, role, tag in missing
    )
    session.commit()
    return len(missing)


def main() -> None:
    password = os.environ.get("SEED_PASSWORD", DEFAULT_PASSWORD)
    with session_factory()() as session:
        created = seed_users(session, password)
    print(f"Created {created} users, {len(SEED_USERS)} expected in total.")


if __name__ == "__main__":
    main()
