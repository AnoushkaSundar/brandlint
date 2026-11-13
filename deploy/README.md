# Deploying the public demo

One server runs the whole stack behind Caddy, which serves HTTPS on one address: the web app at `/`, and the API at `/api`. Demo mode adds one-click sign-in, a role switcher and a guided tour.

**Only for the demo.** The demo accounts share a public password, and anyone with the link can make paid model calls. Use a key with a hard spending limit, and never put real data in it.

## 1. The server

- **Size:** Ubuntu 22.04 or 24.04, 2 vCPU, 4 GB RAM, 30 GB disk.
- **Cloud firewall:** allow only TCP 22, 80 and 443. Docker bypasses the server's own firewall, so the provider's firewall is the one that counts.
- **Docker:** install it with `curl -fsSL https://get.docker.com | sh`. You need Compose 2.24 or later.

## 2. Configure

```bash
git clone https://github.com/AnoushkaSundar/brandlint.git && cd brandlint
cp .env.example .env
```

In `.env`:
- **`JWT_SECRET` and `LITELLM_MASTER_KEY`:** set each to a fresh random value, from `openssl rand -hex 32`.
- **`APP_DB_PASSWORD`:** set a fresh random value, from `openssl rand -hex 24`. It's the password of the restricted database role the API connects as. Use hex, so it needs no escaping in a URL.
- **`SITE_HOST`:** add this line. With no domain, use the server's IP in sslip.io form, such as `SITE_HOST=203.0.113.7.sslip.io`.

Create `.env.litellm` holding `ANTHROPIC_API_KEY=...`. Leave Gemini out: its free tier may use the data.

## 3. Start, then load the demo

```bash
C="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"
$C up -d --build db
$C run --rm --no-deps api alembic upgrade head          # as the owner; creates the app role
$C up -d --build
$C exec api sh -c 'DATABASE_URL=$MIGRATION_DATABASE_URL python -m app.auth.seed'
$C exec api sh -c 'DATABASE_URL=$MIGRATION_DATABASE_URL python -m app.admin.seed --without-rules'
$C exec api python /deploy/preload.py
```

The migration runs first, before the API starts, because the API connects as a role the migration creates. The two seeds run as the database owner, because they name the org themselves and so can't pass the Row-Level Security policy. Everything after that goes through the API, which is how judges use it. See `docs/rls.md`.

The preload ingests and approves the guideline, adds the override history, and reviews the three demo pieces, which takes about a minute. Caddy gets the HTTPS certificate by itself on the first visit.

## 4. Check it

Open `https://<SITE_HOST>/login` and choose **Continue as Creator**. Open the **Demo guide** at the top right, and follow a few steps.

## Opening it to judges: own workspaces

Judges can create their own empty workspace, separate from the Tarnhollow demo. A workspace is a `sandbox` that lasts 7 days, with limits on people, content, uploads, reviews and model calls (`.env.example` lists them). Run these in order, and stop at the first step that fails.

1. **Back up the database**, and keep the file until the release is proven:
   `$C exec -T db pg_dump -U brandlint -Fc brandlint > backup-$(date +%F).dump`
2. **Test the restore once**, on a scratch database, so you know the backup works:
   `$C exec -T db createdb -U brandlint restore_test && $C exec -T db pg_restore -U brandlint -d restore_test --no-owner < backup-<date>.dump && $C exec -T db psql -U brandlint -d restore_test -c "select count(*) from users" && $C exec -T db dropdb -U brandlint restore_test`
3. **Migrate**, as the owner and before the new API starts: `$C run --rm --no-deps api alembic upgrade head`, then `$C up -d --build`. Check the API is connected as `brandlint_app` (see `docs/rls.md`).
4. **Smoke test the demo**: sign in with **Continue as Admin**, open each page, and run `demo/check_demo.py`. It uses the real model.
5. **Turn signup on**: put `MULTI_TENANT_SIGNUP=true` in `.env` and rebuild the web image, because the sign-up form is fixed at build time: `$C up -d --build web api`. The login page now shows **Create your own workspace**.
6. **Smoke test signup**: `API=https://<SITE_HOST>/api python demo/check_workspaces.py`. It makes two workspaces, checks that neither sees the other, and costs nothing. Both workspaces delete themselves in a week.
7. **Delete expired workspaces** on a schedule. Run it once by hand first, then add it to cron:
   `$C exec -T api python -m app.tenancy.expiry` (for example `17 * * * *` for hourly). It deletes each expired sandbox's rows and uploaded files, and never touches the demo.

**Roll back** if step 4 or 6 fails: set `MULTI_TENANT_SIGNUP=false` and rebuild web and api (the form disappears and the API answers 403 to signups). Nothing else needs undoing, because the demo is unaffected. To go back before the organisation migrations, stop the API, restore the dump from step 1 into a fresh database (`pg_restore -d brandlint --clean --if-exists`), and deploy the previous release.

## Turning on CI checks

The CI/CD integration (service tokens, runs, the GitHub Action, the pre-commit hook; see `docs/ci-integration.md`) ships off. Run these in order, and stop at the first step that fails.

1. **Back up the database** and keep the file until the release is proven: `$C exec -T db pg_dump -U brandlint -Fc brandlint > backup-$(date +%F).dump`. This release adds migrations `anoushka_0009` to `anoushka_0011` (service tokens, CI runs and a column on content, CI policies).
2. **Migrate as the owner, before the new API starts:** `$C run --rm --no-deps api alembic upgrade head`, then `$C up -d --build`.
3. **Smoke test with the flag still off:** the demo and `demo/check_demo.py` must behave exactly as before, and `GET /api/ci/whoami` must be a 404.
4. **Turn it on:** put `CI_INTEGRATION_ENABLED=true` in `.env` and rebuild web and api, because the navigation is fixed at build time: `$C up -d --build web api`.
5. **Smoke test CI** against the demo workspace's own stack: `python demo/check_ci.py` (it makes two workspaces, needs `MULTI_TENANT_SIGNUP=true`, and calls no model).
6. **Try a real pull request** on a throwaway repo with the Action (`docs/ci-quickstart.md`): a PR that breaks a rule must fail the required check, be waivable by a reviewer, and then pass.
7. **Add the dogfood workflow's variables** if you want this repo checked too: set the repository variable `BRANDLINT_SERVER` and the secret `BRANDLINT_TOKEN`. Without them the workflow is skipped.

**Roll back** if step 5 or 6 fails: set `CI_INTEGRATION_ENABLED=false` and rebuild web and api. Every `/ci` route, and the CI part of insights, is a 404 again, nothing else changes, and tokens stop working. To undo the migrations: stop the API, `$C run --rm --no-deps api alembic downgrade anoushka_0008`, and restore `backup-<date>.dump` if you need the old rows back. The downgrade drops every token, CI run and policy.

## Reset the demo between sessions

Judges change the shared demo (they approve the newsletter, accept fixes), and the app has no reset button. On the server, from the repository folder:

```bash
bash deploy/reset-demo.sh
```

It backs up the database, resets the Tarnhollow workspace with the app's own admin reset (the demo org only; people and the audit log are kept), reviews the three pieces and the newsletter again with the real model, adds the override history, and lets the governance agent draft its amendment. About a minute, a few cents. Workspaces that visitors made for themselves are not touched.

## Known limits of the live demo

- **Restricted data fails closed.** The local model (Ollama) isn't run on the server, so a `restricted` piece can't be checked by an AI. Code checks still run and flag what they find, and every model-backed check returns UNSURE ("Model check could not run") so a person decides. Nothing goes to the cloud. Checked live: the disclosure lists no models. To show the local route, start Ollama (`--profile local-llm`), which needs about 2 GB more memory.
- **Sign-in is the slow step under load.** Argon2 hashing uses both cores; 40 people signing in at the same second take about 7 seconds each. A few at a time take 2 to 3 seconds.
- **Signups are limited to `SIGNUPS_PER_HOUR` per network address** (30 on the live server), so a venue network can't lock itself out.

## Reset

To clear what judges changed, delete the database volume, then rerun the four setup commands:

```bash
$C down && docker volume rm brandlint_pgdata && $C up -d
```

## Not included

The local model for restricted data needs a GPU. Without it, restricted pieces keep their code checks, and their AI checks come back UNSURE for a reviewer.
