#!/usr/bin/env bash
# check_migrations.sh — static validation of the migration directory (runbook section 6, step 3).
#
# IN PLAIN TERMS: checks the migration files BEFORE any database is touched — names match
# V<NNN>__<desc>.sql, version numbers strictly increase, and destructive SQL is flagged for review.
#
# These are offline checks that run before touching any database:
#   * file names match V<NNN>__<description>.sql
#   * version numbers are unique and strictly increasing
#   * flags obviously destructive statements so they get an explicit rollout/rollback note in review
#
# Checksum-drift detection (never edit an applied migration) is enforced at apply time by
# ci/migrate.py against the per-branch history table, since "applied" is a per-database fact.
set -euo pipefail
DIR="${1:-db/migrations}"

fail=0
prev=0
shopt -s nullglob
files=("$DIR"/*.sql)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "no migrations found in $DIR"; exit 0
fi

for f in $(printf '%s\n' "${files[@]}" | sort); do
  base="$(basename "$f")"
  if [[ ! "$base" =~ ^V([0-9]{3})__.+\.sql$ ]]; then
    echo "FAIL  bad name (expected V<NNN>__<desc>.sql): $base"; fail=1; continue
  fi
  num=$((10#${BASH_REMATCH[1]}))
  if [[ "$num" -le "$prev" ]]; then
    echo "FAIL  version not strictly increasing at $base (saw $num after $prev)"; fail=1
  fi
  prev="$num"
  if grep -Eiq '\b(drop\s+(table|column|schema)|truncate|alter\s+table\s+.*\bdrop\b)' "$f"; then
    echo "WARN  destructive statement in $base — require an explicit rollout/rollback note in the PR"
  fi
  echo "ok    $base"
done

[[ "$fail" -eq 0 ]] && echo "migration checks passed" || { echo "migration checks FAILED"; exit 1; }
