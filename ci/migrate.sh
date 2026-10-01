#!/usr/bin/env bash
# migrate.sh — PostgreSQL migration runner (runbook sections 7 and 10).
#
# Thin, stable CLI surface over ci/migrate.py so CI, local shells, and the guided console all
# call migrations the same way. Owns Postgres execution ONLY; branch/endpoint/connection-ref
# work belongs to ci/lakebase.sh.
#
# Contract:
#   DATABASE_URL        required (or pass --project/--branch/--database for direct SDK connect);
#                       supplied through the process environment, never on the command line
#   MIGRATION_GIT_SHA   Git SHA whose migration set is being applied (recorded in history)
#   ARTIFACT_SHA256     optional for PRs; required after merge to main (recorded in history)
#   --directory DIR     ordered migration directory (default: db/migrations)
#   --validate          dry run: report applied/pending without applying
#
# Example:
#   DATABASE_URL="$LAKEBASE_DATABASE_URL" MIGRATION_GIT_SHA="$(git rev-parse HEAD)" \
#     ./ci/migrate.sh --directory db/migrations
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/migrate.py" "$@"
