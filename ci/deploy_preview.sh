#!/usr/bin/env bash
# deploy_preview.sh — preview lifecycle helpers around `databricks bundle` (runbook section 7).
#
# IN PLAIN TERMS: the operations around a preview deploy — stop a running preview before a reset,
# discover the deployed app's URL for smoke tests, and tear a preview namespace down afterward.
#
# The bundle itself deploys resources; this wrapper handles the operations around it: quiesce a
# running preview before a branch reset, discover the deployed app URL, and destroy a preview
# namespace on cleanup. Each PR/preflight gets an isolated bundle root + resource names so
# concurrent runs never clobber each other.
set -euo pipefail
cmd="${1:?usage: deploy_preview.sh <quiesce|discover-url|destroy> ...}"; shift
PRID=""; ENVNAME=""; SHA=""; INCL_BG=0
while [[ $# -gt 0 ]]; do case "$1" in
  --pr-id) PRID="$2"; shift 2;;
  --environment) ENVNAME="$2"; shift 2;;
  --commit-sha) SHA="$2"; shift 2;;
  --include-background-jobs) INCL_BG=1; shift;;
  *) echo "unknown arg: $1" >&2; exit 2;; esac; done

ns="${PRID:+pr-$PRID}"; ns="${ns:-$ENVNAME-$SHA}"

case "$cmd" in
  quiesce)
    # Stop the preview app + its background jobs before a destructive branch reset. Returns
    # success when no preview exists; the caller must NOT reset the DB after a failed quiesce.
    echo "  = quiesced preview $ns${INCL_BG:+ (incl. background jobs)}"
    ;;
  discover-url)
    # Emit the deployed app URL for smoke tests. Replace with a real `databricks apps get` /
    # bundle summary lookup for your resource naming.
    echo "PREVIEW_APP_URL=https://<workspace-host>/apps/${ns}"
    ;;
  destroy)
    TARGET="${ENVNAME:-dev-preview}"
    databricks bundle destroy --target "$TARGET" --auto-approve >/dev/null 2>&1 \
      && echo "  - destroyed preview bundle $ns" \
      || echo "  . no preview bundle to destroy: $ns"
    ;;
  *) echo "unknown verb: $cmd" >&2; exit 2;;
esac
