"""Tells Postgres which org a transaction belongs to, so Row-Level Security can refuse the rest.

The app-level scoping in `scoped.py` is the first lock. This is the second: every tenant
table has a policy that only shows rows where `org_id` equals the `app.org_id` setting of
the current transaction. If code ever forgets a filter, the database still returns nothing
from another org.

The setting is transaction-local (`set_config(..., true)`), so it can't outlive the
transaction and can't leak to the next user of a pooled connection. It is set:

- when a session that is already bound to an org begins a transaction (`after_begin`), which
  covers every transaction after the first commit, and a background job's sessions;
- when `bind_org` binds a session that is already in a transaction, because the request's
  user is looked up before the org is known (`follow`).

A session with no org sets nothing, and the policies then match no rows at all.
On any database but Postgres this does nothing, so the SQLite tests are unaffected.
"""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

SETTING = "app.org_id"
# The same key `bind_org` stores the org under. Kept here so this module needs no import
# of scoped.py, which imports it.
INFO_KEY = "org_id"


def apply(connection: Connection, org_id: str) -> None:
    """Ties the connection's current transaction to one org."""
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text("SELECT set_config(:setting, :org, true)"),
        {"setting": SETTING, "org": str(org_id)},
    )


@event.listens_for(Session, "after_begin")
def tie_new_transactions_to_the_org(session: Session, transaction, connection) -> None:
    org = session.info.get(INFO_KEY)
    if org is not None:
        apply(connection, org)


def follow(session: Session) -> None:
    """A session that was bound after it began a transaction: tell that transaction too."""
    org = session.info.get(INFO_KEY)
    if org is not None and session.in_transaction():
        apply(session.connection(), org)
