# Multi-tenancy: build plan

Goal: each organisation gets an isolated workspace (its own guidelines, users, roles, content and review data). A judge can sign up, upload their own brand guidelines and review their own drafts without seeing, changing or slowing down the Tarnhollow demo.

This is a security feature. A leak between workspaces is worse than a missing feature, so the isolation tests are written **before** the code that makes them pass.

## Design decisions (locked, don't re-open inside a block)

1. **Shared database, `org_id` on every tenant-owned row.** No schema-per-tenant (migrations, pgvector and Neo4j make that costly).
2. **The org comes only from the signed-in user.** `users.org_id` is the source of truth, like `role` today. Never read an org id from a request body, path, query or header. The JWT carries an `org` claim for convenience, but the database row wins.
3. **Every query on a tenant table goes through a scoped helper** (`scoped(session, Model, org_id)`), not a hand-written `.where(org_id == …)`. A CI check fails if a tenant model is queried any other way.
4. **Postgres Row-Level Security is a second lock**, added after the app-level scoping works. If app code forgets a filter, the database still returns nothing from another org.
5. **404, never 403, for another org's ids**, as `require_review` already does for creators. Ids must not reveal that a row exists.
6. **No sharing across orgs, including the cache.** `review_cache` keys include `org_id`. A hit from another org would leak that someone uploaded the same text, and rules differ per org anyway.
7. **Rulebook versions are per org.** `current_rulebook_version` must filter by org.
8. **Tarnhollow becomes one organisation** (`kind = demo`), created by the migration and holding all existing data. Reset demo only touches that org.
9. **Judge workspaces are `kind = sandbox`:** quotas, a time limit, a per-org LLM budget and rate-limited signup, so one judge can't run up the bill or fill the disk.
10. **Email stays globally unique,** so login needs no workspace picker. The user's org is looked up from their account.
11. **Uploaded guidelines are untrusted input.** They go through the existing injection defences in the ingest agent. Add a test that a guideline containing "ignore previous instructions" can't change a verdict.
12. **Ship behind a flag.** `MULTI_TENANT_SIGNUP=false` until block 9, so the live demo never changes mid-build.

## Tables that need `org_id` (inventory, from the repo)

- **Product:** `users`, `content`, `content_versions`, `reviews`, `review_state_log`, `decisions`, `fix_offers`, `comments`, `audit_log`, `rules`, `facts`, `terms`, `assets`, `ingest_jobs`, `gaps`
- **Engine:** `chunks`, `claim_units`, `findings`, `review_cache`
- **Memory, gateway, governance:** `edges`, `gateway_log`, `token_vault`, `proposals`, `spot_checks`, `eval_runs`

Not tables but also tenant-scoped: uploaded files (`content/storage.py`), the Neo4j graph, the SSE findings stream, the gateway confidential-term deny-list (built from the org's own facts), masking vault scope, LiteLLM budget.

## Rules for every block

- One branch and one PR per block. Branch name `feat/<person>-mt-<n>-<name>`.
- Write the failing tests first, then the code. Show them failing, then passing.
- Each migration has an upgrade and a downgrade, and `test_migrations.py` covers both.
- Run `ruff`, the full `pytest` and the LLM-import guard before opening the PR.
- Do not edit the other person's folders (see `CLAUDE.md`). If a block needs that, stop and say what's needed.
- End every block with a report: what works, what's left, what could still leak.
- Don't deploy until the block's gate passes. Take a database backup before any block that has a migration.

---

## Block 0: Isolation test harness and table inventory (Alapan)

**Goal:** prove isolation before building it.

- `api/tests/tenancy/` with fixtures: two orgs, each with an admin, reviewer and creator, plus content, a review, findings, rules, facts and a precedent.
- A parametrised test that calls **every** GET/POST route as org B using org A's ids and expects 404 (or an empty list for list endpoints). Generate the route list from the FastAPI app so new routes are covered automatically.
- A test that fails if a model with a table is missing from the tenant allow-list or the shared-table list (`organizations` only).
- Mark them `xfail(strict=True)` for now, so each later block flips its share to passing.

**Gate:** CI is green with the xfails in place, and the route list matches `docs`.

## Block 1: Organisations and users (Anoushka)

**Goal:** the org exists and every user belongs to one. Use `make_org` and `org_kwargs` in `api/tests/tenancy/world.py` as the test seam, and adjust them if `organizations` needs more columns. Block 0's 2 tests for this block should flip to passing.

- `organizations` table: `id`, `name`, `slug` (unique), `kind` (`demo` | `sandbox`), `created_at`, `expires_at` (nullable), `status` (`active` | `suspended`).
- `users.org_id` (migration `anoushka_0006_*`): add nullable, create the "Tarnhollow" demo org, backfill every user, then set NOT NULL with an index. Do it in one migration, in that order.
- Add `org` to the token claims in `auth/security.py`; `current_user` reloads the user and checks the org is `active`.
- Update `auth/seed.py` to seed users into the demo org.

**Checks:** migration up/down test with existing rows; a suspended org can't log in; token with a forged org claim still gets the user's real org.
**Gate:** the live demo logins still work after the migration on a copy of production data.

## Block 2: Request context and scoped helper (Anoushka)

**Goal:** one correct way to query tenant data, before anything uses it.

- `app/tenancy/` with `current_org` (dependency), `scoped(session, Model)` (adds the org filter and refuses models without `org_id`), and `org_id` auto-fill on insert for tenant models.
- A CI check (extend `scripts/check_llm_imports.sh` style, or a pytest) that flags `session.scalar/scalars/execute/get` on tenant models outside `app/tenancy/`.
- Document the pattern in `CLAUDE.md`.

**Checks:** unit tests for the helper; it raises if a model has no `org_id`; `session.get(Model, id)` is replaced by a scoped get (a plain `get` ignores filters).
**Gate:** no behaviour change yet; all existing tests pass.

## Block 3: Scope the product tables (Anoushka)

**Goal:** content, workflow, brand admin and insights are per org.

- Migration `anoushka_0007_*`: add `org_id` to the product tables above (nullable, backfill to the demo org, NOT NULL, indexes, composite unique constraints where needed, e.g. `terms` unique per org).
- **Rules and facts keys:** they use `(id, version)` as the primary key today, so two orgs can't both have "R1". Change both to `(org_id, id, version)`, and update every foreign key or lookup that uses the old key.
- Convert `content/`, `workflow/`, `admin/`, `insights/` queries to the scoped helper.
- `current_rulebook_version` and `rulebook_at` take an org.
- Move uploaded files to `<org_id>/…` paths in `content/storage.py`; the file route checks the org before streaming.

**Checks:** the Block 0 route test now passes for these routers (14 tables and 32 routes under `/admin`, `/content`, `/insights`, `/workflow`); two orgs can each have rule "R1" version 1 without clashing; approving a rule in org A doesn't bump org B's rulebook version.
**Gate:** the existing Playwright flow passes for the demo org.

## Block 4: Scope the engine, memory, gateway and governance (Alapan)

**Goal:** the AI side never mixes orgs.

- Migration `alapan_0005_*`: `org_id` on `chunks`, `claim_units`, `findings`, `review_cache`, `edges`, `gateway_log`, `token_vault`, `proposals`, `spot_checks`, `eval_runs`.
- Pass the org through `clients/engine.py`, `load_brand`, the graph, and the cache. `cache_key` includes `org_id`.
- `token_vault.scope` stays the review id, but a review id from another org must not resolve.
- The gateway deny-list is built from the org's own facts and terms only.
- Impact, precedents, graph (Postgres and Neo4j sync, tag nodes with `org_id`) and `/memory/*` return only the org's data.
- **`edges.sync` rebuilds the graph for all content at once.** Block 0 excluded `edges` from the write checks as derived data, so scope the sync to one org here and add its own cross-org test (org B can't trigger or alter org A's edges).
- **Same text, two orgs:** add the test that identical chunk text in two orgs never shares a cache entry. Block 0 doesn't cover it.
- The SSE findings stream, Replay and the masking-preview check the org through `require_review`.
- Governance agent, spot-check sampler and eval runner run per org; `eval/` fixtures belong to the demo org.

**Checks:** the identical chunk text in two orgs gives two cache rows and never a cross-org hit; Replay of org A's finding from org B returns 404; precedents from org A never appear in org B; the remaining xfails in Block 0 flip to passing and the xfail markers are removed.
**Gate:** the full isolation suite is green with no xfail left (10 tables and 13 routes under `/engine`, `/gateway`, `/governance`, `/memory`). Replay, proposal approval and gap-log writes from another org must now fail, since Block 0 found them leaking.

## Block 5: Postgres Row-Level Security (Alapan)

**Goal:** a forgotten filter can't leak.

- Migration enabling and **forcing** RLS on every tenant table, with a policy `org_id = current_setting('app.org_id')::uuid`.
- The API sets `SET LOCAL app.org_id` at the start of each request's transaction (in `get_session`, from the authenticated user). Background jobs set it explicitly.
- The app must connect as a non-owner, non-superuser role (RLS is bypassed by owners without FORCE, and always by superusers). Add that role in the migration and in `deploy/docker-compose.prod.yml`.
- A small allow-listed admin path for cross-org jobs (expiry cleanup) using a separate role.

**Checks:** a deliberately unscoped query in a test returns zero rows from another org; a request with no org set returns nothing; migrations and `preload.py` still work under the new role.
**Gate:** the isolation suite is green with RLS on, and a bad-query test proves the backstop works.

## Block 6: Per-org seed, preload and reset (Anoushka)

**Goal:** demo data lives in the demo org only, and a new org starts clean.

- `auth/seed.py`, `demo/build_demo.py`, `deploy/preload.py` and `demo/seed_history.py` take an org and target the demo org by default.
- "Reset demo" deletes and re-seeds only the demo org, and is refused for any other org.
- A new org starts empty: no rules, no facts, no content. An empty rulebook must stay a clear error (see `RulebookNotFound`), never a silent pass.
- Optional "load sample guidelines" button that copies the Tarnhollow guidelines into the org as a starting point.

**Checks:** reset in org A leaves org B untouched (row counts before and after); a review in an empty org is blocked with a helpful message.

## Block 7: Workspace signup and user management (Anoushka, API; Alapan, limits)

**Goal:** a judge goes from zero to their own workspace in under a minute.

- `POST /orgs` (public, rate limited): creates a `sandbox` org plus its first admin from name, email and password. Honour `MULTI_TENANT_SIGNUP`.
- Admin-only `POST /admin/users` invites users into the admin's own org with a role. An admin can't create users in another org or grant a role above their own (no new `admin` unless they are one).
- Last-admin protection: an org can't remove or demote its only admin.
- **Abuse controls (Alapan):** per-org quotas (users, content items, upload size, reviews per day), signup rate limit per IP, `expires_at` of 7 days, and a LiteLLM budget per org (virtual key or a per-org counter in `gateway_log`, enforced in `llm.call`). Over-quota returns a clear 429.

**Checks:** signup creates exactly one org and one admin in a single transaction; the same email twice is rejected; quotas and the LLM budget stop a script; suspending an org blocks its users at once.

## Block 8: Frontend (Anoushka)

**Goal:** the UI makes the separation obvious.

- Login page: "Explore the Tarnhollow demo" and "Create your own workspace" side by side.
- Workspace name in the header and in the page title; the demo org shows a "Demo workspace" badge.
- Onboarding checklist for an empty org: upload guidelines, review and approve rules, invite a teammate, upload the first draft.
- Admin page for users and roles; sandbox expiry banner.
- Update `web/lib/contracts.ts` and the guided tour, so the tour only runs in the demo org.

**Checks:** Playwright with two browsers and two orgs, each creating a rule; neither sees the other's; the tour never appears in a sandbox.

## Block 9: Hardening and rollout (both)

**Goal:** safe to open to judges.

- **Red-team pass (Alapan):** try every id-guessing and path-swapping attack from a second org, including SSE, Replay, file downloads, graph and precedents; try a prompt-injected guideline; try oversized and malformed uploads.
- **Expiry job (Alapan):** deletes expired sandbox orgs and their files, using the admin role from Block 5.
- **Rollout runbook (Alapan):** database backup, migrate, smoke test, flip `MULTI_TENANT_SIGNUP`, and the rollback steps. Add it to `deploy/README.md`.
- **Docs (both):** update `CLAUDE.md`, `docs/design.md` and the README, including the new test commands. `docs/contracts.md` lists only 20 of the 52 routes, so add the missing ones and tighten the docs test from "docs ⊆ app" to equality.
- Tag `v1.1`.

**Gate:** the full isolation suite, Playwright two-org test and the demo script pass on the live server, and the backup restore was tested once.

---

## Order and dependencies

0 → 1 → 2 → (3 and 4 in parallel; they touch different folders) → 5 → 6 → 7 → 8 → 9. Block 8 can start once block 7's API exists. Blocks 3 and 4 should merge close together so the isolation suite goes green in one go.
