#!/bin/sh
set -eu

PACKET_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PACKET_DIR"

python reproduce_review_metrics.py

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 -c MANIFEST.sha256
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum -c MANIFEST.sha256
else
  echo "No SHA-256 checker found (shasum or sha256sum required)" >&2
  exit 1
fi

echo "PASS: metrics and bundle hashes verified"
