#!/usr/bin/env bash
# build_eval_set.sh — freeze the gold passages for the featured eval queries into
# ui/static/eval_set.json, which powers the "Golden eval set" page.
#
# Like build_fixtures.sh, it runs as the Db2 instance owner over a LOCAL
# connection. Cheap (no embedding calls) — just reads chunk text by id.
# Re-run it whenever the corpus or the featured query set changes.
#
#   ./ui/build_eval_set.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # ui/
REPO="$(dirname "$HERE")"
OWNER="${DB2_INSTANCE_OWNER:-db2inst1}"

# Stage files the instance owner can read (it can't read /home/<you>).
cp "$HERE/build_eval_set.py" "$HERE/queries.json" "$REPO/scripts/hybrid_core.py" /tmp/
chmod 644 /tmp/build_eval_set.py /tmp/queries.json /tmp/hybrid_core.py
rm -f /tmp/eval_set.json

sudo -iu "$OWNER" bash -lc 'DB2_HOST=local python3 /tmp/build_eval_set.py'

# Publish the data the static UI serves.
mkdir -p "$HERE/static"
cp /tmp/eval_set.json "$HERE/static/eval_set.json"
echo "published -> ui/static/eval_set.json"
