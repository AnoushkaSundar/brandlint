# Row-Level Security: the database is the second lock

The app scopes every tenant query by org (`app/tenancy`). Row-Level Security (RLS) is the backstop: if code ever forgets a filter, **Postgres still returns nothing from another org**.

## How it works

- **A policy on every tenant table** (all 25, `users` included: see "`users`"): a row is visible, and can be written, only when its `org_id` equals the `app.org_id` setting of the current transaction. With no setting, nothing matches. The policy is `FORCE`d, so the table's owner is held to it too.
- **The setting is set per transaction** (`set_config(..., true)`), so it can't outlive the transaction or leak to the next user of a pooled connection. `app/tenancy/rls.py` sets it when a bound session begins a transaction, and when `bind_org` binds a session that already began one (the user is looked up before the org is known).
- **The API connects as `brandlint_app`:** not a superuser, not able to bypass RLS, and owner of no table. Superusers and owners bypass RLS, so connecting as either would switch the lock off.
- **Only Postgres.** On any other database the hook does nothing, so the SQLite tests are unaffected.

## Roles

| Role | Used for | RLS applies |
|---|---|---|
| `brandlint_app` | the API, at runtime | yes |
| `brandlint` (the owner) | migrations and the two seeds, through `MIGRATION_DATABASE_URL` | no, while it is a superuser, as in the compose file |

The migration creates `brandlint_app` with no login, and gives it one when `APP_DB_PASSWORD` is set while it runs. The password reaches the server as a setting that the server quotes, never spliced into a statement.

## Rolling it out

1. **Back up the database.**
2. Put `APP_DB_PASSWORD` in `.env` (`openssl rand -hex 24`).
3. Run the migration **before** the API starts: `$C run --rm --no-deps api alembic upgrade head`. It uses `MIGRATION_DATABASE_URL`, so it works before the app role exists.
4. Start the API. Check it is connected as the restricted role:
   `docker compose exec db psql -U brandlint -d brandlint -c "select usename, count(*) from pg_stat_activity where datname='brandlint' group by 1"` must show `brandlint_app`, and never `brandlint`, for the API's connections.
5. **Rollback:** stop the API, run `alembic downgrade alapan_0005`, and point `DATABASE_URL` back at the owner. The downgrade drops the policies and the role, and fails while the API is still connected as it.

## `users`

Signing in finds a user by email, and every request finds its user by id, **before any org is known**. So `users` has the same policy as the other tables, plus one way through: a transaction that sets `app.auth` to `on` can read users across orgs. `auth_lookup(session)` in `app/tenancy/rls.py` sets it, only the two lookups made before the org is known use it (`current_user` and `login`), and it is cleared as the block ends. Writes are held to the org rule only (`anoushka_0008`).

## Things to know

- **The seeds run as the owner.** `app.auth.seed` and `app.admin.seed` pass the org explicitly instead of binding a session, so as `brandlint_app` they would be refused. `preload.py` talks to the API and is unaffected.
- **A non-superuser owner is held to the policy too** (`FORCE`). If your owner isn't a superuser, a later migration that changes tenant rows must first run `SET LOCAL app.org_id = '<org>'`.
- **Cross-org jobs** (the expiry cleanup in Block 9) will need their own role with `BYPASSRLS`. It isn't created here, because nothing uses it yet.
- **The default owner password** in `docker-compose.yml` is `brandlint`. The database isn't published in the production overlay, so only the other containers reach it. Change `POSTGRES_PASSWORD` anyway for a real deployment.
- **Why the policy compares `uuid`:** an unset or empty setting becomes NULL, and NULL matches nothing. A malformed setting is a cast error, which also returns nothing.

## Tests

`api/tests/test_rls.py`. The first half runs everywhere. The second half needs a real Postgres: set `RLS_TEST_DATABASE_URL` to a superuser URL, such as `postgresql+psycopg://brandlint:brandlint@db:5432/postgres`. Each run builds a scratch database and a throwaway role, and removes both. It proves:

- a request that never named its org sees nothing, in all 24 tables;
- a query with **no org filter at all** on a bound session returns only that org's rows;
- the setting survives a commit in the same session, and binding after the first query takes effect at once;
- the setting never reaches the next user of a pooled connection;
- the database refuses to write a row for another org, and can't change or delete another org's rows;
- a background thread's sessions see only their own org;
- the app role is not a superuser, can't bypass RLS and owns no table;
- the migration downgrades and upgrades again.

**CI doesn't run the Postgres half yet.** Add a Postgres service to the `python` job in `.github/workflows/ci.yml`, then set the variable. Changing a workflow file needs a login with the `workflow` permission, so it isn't in this PR:

```yaml
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env: { POSTGRES_PASSWORD: postgres }
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-timeout 3s --health-retries 10
    env:
      RLS_TEST_DATABASE_URL: postgresql+psycopg://postgres:postgres@localhost:5432/postgres
```
