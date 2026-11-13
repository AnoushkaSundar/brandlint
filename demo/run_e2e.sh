#!/usr/bin/env bash
# The whole product end to end, in a real browser: the real web app, a real API on a fresh
# Postgres as the restricted role with Row-Level Security on, and the real `brandlint` command.
# Two workspaces, two browsers. The mock engine is used, so no model is called.
#
#   PYTHON=path/to/python bash demo/run_e2e.sh
#
# Needs Docker, Node, and a Python with the API's requirements and the CLI's (httpx, pyyaml).
set -u
PYTHON="${PYTHON:-python}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$(mktemp -d)"
cleanup() {
  [ -f "$LOGS/api.pid" ] && kill "$(cat "$LOGS/api.pid")" 2>/dev/null
  [ -f "$LOGS/web.pid" ] && kill "$(cat "$LOGS/web.pid")" 2>/dev/null
  docker rm -f e2e-pg >/dev/null 2>&1
}
trap cleanup EXIT

docker rm -f e2e-pg >/dev/null 2>&1
docker run -d --name e2e-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=e2e -p 55435:5432 pgvector/pgvector:pg16 >/dev/null
sleep 9

cd "$HERE/api" || exit 1
export JWT_SECRET=e2e-secret-e2e-secret-e2e-secret-12 PYTHONPATH=.
OWNER="postgresql+psycopg://postgres:pw@localhost:55435/e2e"
APP="postgresql+psycopg://brandlint_app:apppw@localhost:55435/e2e"
DATABASE_URL=$OWNER MIGRATION_DATABASE_URL=$OWNER APP_DB_PASSWORD=apppw "$PYTHON" -m alembic upgrade head >/dev/null 2>&1 || { echo "migration failed"; exit 1; }
DATABASE_URL=$OWNER "$PYTHON" -m app.auth.seed >/dev/null
(DATABASE_URL=$APP WEB_ORIGIN=http://localhost:3100 MULTI_TENANT_SIGNUP=true CI_INTEGRATION_ENABLED=true \
  CI_BASE_URL=http://localhost:3100 SIGNUPS_PER_HOUR=500 "$PYTHON" -m uvicorn app.main:app --port 8000 > "$LOGS/api.log" 2>&1 & echo $! > "$LOGS/api.pid")

cd "$HERE/web" || exit 1
NEXT_PUBLIC_API_URL=http://localhost:8000 NEXT_PUBLIC_CI_ENABLED=true NEXT_PUBLIC_MULTI_TENANT_SIGNUP=true \
  NEXT_PUBLIC_DEMO_MODE=false npx next build > "$LOGS/build.log" 2>&1 || { tail -20 "$LOGS/build.log"; exit 1; }
(npx next start -p 3100 > "$LOGS/web.log" 2>&1 & echo $! > "$LOGS/web.pid")
for _ in $(seq 1 30); do curl -sf -o /dev/null http://localhost:3100/login && break; sleep 2; done

E2E_PYTHON="$PYTHON" npx playwright test -c playwright.e2e.config.ts
code=$?
echo "API tracebacks: $(grep -ci traceback "$LOGS/api.log")"
exit $code
