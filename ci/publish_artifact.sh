#!/usr/bin/env bash
# publish_artifact.sh — publish the immutable artifact and record its digest (runbook sections 7.2, 9).
#
#   ./ci/publish_artifact.sh --sha "$GITHUB_SHA" --output "$GITHUB_OUTPUT"
#
# Emits artifact_uri and artifact_sha256 as step outputs; QA/PROD fetch and verify EXACTLY these.
# The URI scheme here is a local file store for the template; point ARTIFACT_STORE at your OCI
# registry or package repo in a real deployment.
set -euo pipefail
SHA=""; OUT="/dev/stdout"
while [[ $# -gt 0 ]]; do case "$1" in
  --sha) SHA="$2"; shift 2;;
  --output) OUT="$2"; shift 2;;
  *) echo "unknown arg: $1" >&2; exit 2;; esac; done
: "${SHA:?--sha required}"

STORE="${ARTIFACT_STORE:-$PWD/.artifacts}"; mkdir -p "$STORE"
SRC="dist/app-${SHA}.tar.gz"
[[ -f "$SRC" ]] || { echo "artifact not built: $SRC (run ci/build.sh first)" >&2; exit 1; }

cp "$SRC" "$STORE/"
DIGEST="$(shasum -a 256 "$SRC" | awk '{print $1}')"
URI="file://$STORE/app-${SHA}.tar.gz"

{ echo "artifact_uri=$URI"; echo "artifact_sha256=$DIGEST"; } >> "$OUT"
echo "  + published $URI"
echo "  + sha256   $DIGEST"
