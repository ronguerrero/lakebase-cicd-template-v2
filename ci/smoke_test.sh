#!/usr/bin/env bash
# smoke_test.sh — minimal post-deploy health check (runbook sections 6-7).
#
# IN PLAIN TERMS: a quick check after a deploy that the database the app points at is reachable and
# carries the expected schema (migration history + users). Extend with an HTTP probe of the app.
#
# Confirms the database the app is pointed at is reachable and carries the expected schema.
# Uses DATABASE_URL (the branch the preview/stable app is bound to). Extend with an HTTP probe
# of APP_BASE_URL for the deployed app's own health endpoint.
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL must be set}"

python3 - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=60) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM app.schema_migrations")
        applied = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM app.users")
        users = cur.fetchone()[0]
print(f"  = smoke ok: {applied} migrations applied, {users} users reachable")
PY

if [[ -n "${APP_BASE_URL:-}" ]]; then
  echo "  = (would probe $APP_BASE_URL/health here)"
fi
