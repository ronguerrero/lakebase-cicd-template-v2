#!/usr/bin/env bash
# build.sh — build the application artifact exactly once from a Git SHA (runbook sections 7.2, 9).
#
# IN PLAIN TERMS: packages the app into one tarball from a Git SHA so every environment deploys the
# identical bytes (verified later by digest) instead of each stage rebuilding from source.
#
# "Build once" is the rule: QA and PROD deploy the SAME bytes, verified by digest, rather than
# re-checking-out the SHA and rebuilding. This produces a deterministic tarball of app/ under dist/.
set -euo pipefail
SHA="${1:?usage: build.sh <git-sha>}"
mkdir -p dist
OUT="dist/app-${SHA}.tar.gz"

# Deterministic archive: sorted entries, fixed mtime/owner, so identical source -> identical bytes.
tar --sort=name --mtime='UTC 2020-01-01' --owner=0 --group=0 --numeric-owner \
    -czf "$OUT" app db/migrations 2>/dev/null \
  || tar -czf "$OUT" app db/migrations   # BSD tar fallback (local macOS); CI uses GNU tar
echo "  + built $OUT"
echo "$OUT"
