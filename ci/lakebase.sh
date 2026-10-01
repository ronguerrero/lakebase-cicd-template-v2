#!/usr/bin/env bash
# lakebase.sh — Lakebase control-plane wrapper (runbook sections 5, 6, 7).
#
# IN PLAIN TERMS: creates/destroys Lakebase branches and hands out a database connection URL for a
# chosen branch+database. Every stage that touches a branch or database goes through here. It never
# prints a credential to a normal log. All real work is delegated to ci/lakebase_api.py.
#
# Centralizes CLI/SDK version differences, readiness polling, connection discovery, retries,
# reset, and cleanup so workflow files stay declarative. All real work is done by
# ci/lakebase_api.py (databricks-sdk, projects/branches model). Authentication is ambient:
# in CI it comes from GitHub OIDC -> service principal; locally from DATABRICKS_CONFIG_PROFILE.
#
# None of these verbs ever prints a credential or database URL to a normal log. `wait-and-export`
# and `export-stable-connection` emit a single KEY=VALUE line meant for `>> "$GITHUB_ENV"`.
#
# Verbs:
#   init <project>                                   one-time platform setup: project + the single
#                                                    long-lived `production` branch + its three
#                                                    databases (app_dev_db / app_qa_db / app_prod_db)
#   prepare-ci-branch <project> <branch> \
#       --source-branch production \
#       --database <db> [--reset-existing] [--ttl S] create/reset an ephemeral child of production;
#                                                    it contains all three dbs, caller selects one
#   create-preflight <branch> <project> \
#       --source-branch production [--ttl S]         create an ephemeral rehearsal child of production
#   wait-and-export <project> <branch> <database>    wait for endpoint, emit LAKEBASE_DATABASE_URL=
#   export-stable-connection <project> <branch> <db> emit LAKEBASE_STABLE_DATABASE_URL=
#   publish-connection-ref <branch> <db> <ref>       emit the non-secret LAKEBASE_CONNECTION_REF=
#   delete-connection-ref <ref>                      idempotent teardown of the ref mapping
#   delete-ci-branch <branch> <project>              idempotent branch delete
#   schema-diff <project> <branch> <database>        print the app schema for PR review
#   tree <project>                                   human-readable branch tree
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=(python3 "$HERE/lakebase_api.py")

# Strip any "projects/" prefix so callers can pass either form.
proj() { echo "${1##*/}"; }

cmd="${1:?usage: lakebase.sh <verb> ...}"; shift || true

case "$cmd" in
  init)
    # One long-lived branch `production` hosts all THREE databases. There is no long-lived
    # dev or qa branch — dev/qa/prod are separated by database (and by role), not by branch.
    P="$(proj "${1:?project}")"
    "${PY[@]}" init-project --project "$P"
    "${PY[@]}" ensure-branch --project "$P" --branch production --no-expiry
    "${PY[@]}" ensure-database --project "$P" --branch production --database app_dev_db
    "${PY[@]}" ensure-database --project "$P" --branch production --database app_qa_db
    "${PY[@]}" ensure-database --project "$P" --branch production --database app_prod_db
    ;;

  ensure-database)
    # passthrough: ./ci/lakebase.sh ensure-database <project> <branch> <database>
    P="$(proj "${1:?project}")"; B="${2:?branch}"; D="${3:?database}"
    "${PY[@]}" ensure-database --project "$P" --branch "$B" --database "$D"
    ;;

  prepare-ci-branch)
    P="$(proj "${1:?project}")"; B="${2:?branch}"; shift 2
    SRC="production"; DB="app_dev_db"; RESET=0; TTL=14400
    while [[ $# -gt 0 ]]; do case "$1" in
      --source-branch) SRC="$2"; shift 2;;
      --database) DB="$2"; shift 2;;
      --reset-existing) RESET=1; shift;;
      --ttl) TTL="$2"; shift 2;;
      *) echo "unknown arg: $1" >&2; exit 2;; esac; done
    [[ "$RESET" -eq 1 ]] && "${PY[@]}" delete-branch --project "$P" --branch "$B"
    "${PY[@]}" ensure-branch --project "$P" --branch "$B" --source "$SRC" --ttl "$TTL"
    # child inherits $DB from $SRC by copy-on-write; nothing else to create
    ;;

  create-preflight)
    B="${1:?branch}"; P="$(proj "${2:?project}")"; shift 2
    SRC="production"; TTL=14400
    while [[ $# -gt 0 ]]; do case "$1" in
      --source-branch) SRC="$2"; shift 2;;
      --ttl) TTL="$2"; shift 2;;
      *) echo "unknown arg: $1" >&2; exit 2;; esac; done
    "${PY[@]}" ensure-branch --project "$P" --branch "$B" --source "$SRC" --ttl "$TTL"
    ;;

  wait-and-export)
    P="$(proj "${1:?project}")"; B="${2:?branch}"; DB="${3:?database}"
    "${PY[@]}" wait-endpoint --project "$P" --branch "$B" >&2
    "${PY[@]}" export-url --project "$P" --branch "$B" --database "$DB" --var LAKEBASE_DATABASE_URL
    ;;

  export-stable-connection)
    P="$(proj "${1:?project}")"; B="${2:?branch}"; DB="${3:?database}"
    "${PY[@]}" wait-endpoint --project "$P" --branch "$B" >&2
    "${PY[@]}" export-url --project "$P" --branch "$B" --database "$DB" --var LAKEBASE_STABLE_DATABASE_URL
    ;;

  publish-connection-ref)
    B="${1:?branch}"; DB="${2:?database}"; REF="${3:?ref}"
    # The ref is a logical, non-secret identifier. In a real deployment this also binds the
    # endpoint/branch metadata in the approved secret manager under the branch's TTL/owner.
    echo "  = connection ref published: $REF -> $B/$DB" >&2
    echo "LAKEBASE_CONNECTION_REF=$REF"
    ;;

  delete-connection-ref)
    REF="${1:?ref}"
    echo "  - connection ref removed (idempotent): $REF" >&2
    ;;

  delete-ci-branch)
    B="${1:?branch}"; P="$(proj "${2:?project}")"
    "${PY[@]}" delete-branch --project "$P" --branch "$B"
    ;;

  schema-diff)
    P="$(proj "${1:?project}")"; B="${2:?branch}"; DB="${3:?database}"
    CI_DIR="$HERE" python3 - "$P" "$B" "$DB" <<'PY'
import sys, os
sys.path.insert(0, os.environ["CI_DIR"])
from lakebase_api import client, connect
p, b, db = sys.argv[1], sys.argv[2], sys.argv[3]
conn = connect(client(), p, b, db)
with conn.cursor() as cur:
    cur.execute("""
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns WHERE table_schema='app'
        ORDER BY table_name, ordinal_position""")
    print(f"schema of app on {b}/{db}:")
    for t, c, d, n in cur.fetchall():
        print(f"  {t}.{c}  {d}{'' if n=='YES' else ' NOT NULL'}")
conn.close()
PY
    ;;

  tree)
    "${PY[@]}" tree --project "$(proj "${1:?project}")"
    ;;

  *)
    echo "unknown verb: $cmd" >&2; exit 2;;
esac
