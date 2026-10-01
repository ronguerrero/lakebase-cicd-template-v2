#!/usr/bin/env bash
# fetch_artifact.sh — retrieve and verify the exact published artifact (runbook sections 7.2, 9).
#
#   ./ci/fetch_artifact.sh --uri "$ARTIFACT_URI" --sha256 "$ARTIFACT_SHA256"
#
# Fails if the digest does not match: QA and PROD must deploy the identical bytes that were built
# once after merge. Re-checking-out the SHA and rebuilding is NOT acceptable proof.
set -euo pipefail
URI=""; WANT=""
while [[ $# -gt 0 ]]; do case "$1" in
  --uri) URI="$2"; shift 2;;
  --sha256) WANT="$2"; shift 2;;
  *) echo "unknown arg: $1" >&2; exit 2;; esac; done
: "${URI:?--uri required}"; : "${WANT:?--sha256 required}"

mkdir -p dist
case "$URI" in
  file://*) cp "${URI#file://}" dist/ ;;
  oci://*|https://*) echo "fetch $URI with your registry client here" >&2; exit 1 ;;
  *) echo "unsupported artifact URI: $URI" >&2; exit 1 ;;
esac

LOCAL="dist/$(basename "$URI")"
GOT="$(shasum -a 256 "$LOCAL" | awk '{print $1}')"
if [[ "$GOT" != "$WANT" ]]; then
  echo "DIGEST MISMATCH: expected $WANT, got $GOT" >&2; exit 1
fi
echo "  = verified $LOCAL ($GOT)"
