#!/usr/bin/env bash
# Puts the public demo back to its starting state, for the next judge or session.
#
#   bash deploy/reset-demo.sh
#
# Run it on the server, from the repository folder. It:
#   1. backs up the database (kept in ~/backups, newest 10),
#   2. resets the Tarnhollow demo workspace (the app's own admin reset: it only ever touches
#      the demo org, and keeps the people and the audit log),
#   3. reloads the demo: reviews the three pieces and the newsletter with the real model,
#   4. adds the override history, and lets the governance agent draft its amendment.
#
# It takes about a minute and costs a few cents of model use. Workspaces that visitors made
# for themselves are not touched. Safe to run again.
set -euo pipefail

cd "$(dirname "$0")/.."
C="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"
SITE_HOST="$(grep -E '^SITE_HOST=' .env | cut -d= -f2-)"
[ -n "$SITE_HOST" ] || { echo "SITE_HOST is not set in .env"; exit 1; }
API="https://${SITE_HOST}/api"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

step() { printf '\n== %s\n' "$1"; }

step "1/4 Backup"
mkdir -p ~/backups
FILE=~/backups/demo-reset-$(date +%F-%H%M).dump
$C exec -T db pg_dump -U brandlint -Fc brandlint > "$FILE"
echo "saved $FILE ($(du -h "$FILE" | cut -f1))"
ls -1t ~/backups/demo-reset-*.dump | tail -n +11 | xargs -r rm --

step "2/4 Reset the demo workspace"
curl -fsS -c "$JAR" -o /dev/null -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@tarnhollow.example","password":"brandlint-demo"}'
curl -fsS -b "$JAR" -X POST "$API/admin/demo/reset"; echo

step "3/4 Review the demo pieces and add the override history"
$C exec -T api python /deploy/preload.py
# preload skips the history when the rulebook is already approved, which it is after a reset.
$C exec -T api python -c '
import sys
sys.path.insert(0, "/deploy"); sys.path.insert(0, "/demo")
import preload, seed_history
sys.exit(seed_history.main())'

step "4/4 Let the governance agent draft its amendment"
curl -fsS -b "$JAR" -X POST "$API/governance/run" --max-time 280 \
  | python3 -c 'import sys,json; [print(p["rule_id"], p["status"]) for p in json.load(sys.stdin)]'

printf '\nDemo reset. Open https://%s/judge/\n' "$SITE_HOST"
