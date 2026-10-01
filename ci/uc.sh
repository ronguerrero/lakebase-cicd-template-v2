#!/usr/bin/env bash
# uc.sh — Unity Catalog preview-namespace helpers (runbook section 5).
#
# IN PLAIN TERMS: creates/deletes the per-PR and per-preflight Unity Catalog schemas (lakehouse
# scratch space). These UC objects are separate from the Postgres application database.
#
# UC catalogs (app_dev/app_qa/app_prod) hold ordinary lakehouse objects and are PARALLEL to
# Lakebase, not bound to it. CI owns creation/deletion of per-PR and per-preflight schemas;
# humans never create objects in the stable app schemas. Uses the Databricks CLI with ambient
# auth. app_dev.pr_<id> is UC-only scratch space — it is NOT the application's transaction DB.
set -euo pipefail
cmd="${1:?usage: uc.sh <create-schema|delete-schema> --catalog C --schema S}"; shift
CAT=""; SCH=""
while [[ $# -gt 0 ]]; do case "$1" in
  --catalog) CAT="$2"; shift 2;;
  --schema)  SCH="$2"; shift 2;;
  *) echo "unknown arg: $1" >&2; exit 2;; esac; done
: "${CAT:?--catalog required}"; : "${SCH:?--schema required}"

case "$cmd" in
  create-schema)
    databricks schemas create "$SCH" "$CAT" >/dev/null \
      && echo "  + UC schema created: $CAT.$SCH" \
      || echo "  = UC schema exists: $CAT.$SCH"
    ;;
  delete-schema)
    # idempotent: a missing schema on cleanup must not fail the workflow
    databricks schemas delete "$CAT.$SCH" --force >/dev/null 2>&1 \
      && echo "  - UC schema deleted: $CAT.$SCH" \
      || echo "  . no UC schema to delete: $CAT.$SCH"
    ;;
  *) echo "unknown verb: $cmd" >&2; exit 2;;
esac
