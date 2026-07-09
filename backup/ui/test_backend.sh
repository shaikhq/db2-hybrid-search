#!/usr/bin/env bash
# test_backend.sh — run the UI backend tests in-process (no server, no port).
#
# Stages the UI backend + test alongside the hybrid_search package, then runs them as the Db2
# instance owner over a LOCAL connection (same as build_fixtures.sh). Calls the
# FastAPI route functions and the search engine directly, so it tests the backend
# without uvicorn or the browser in the way.
#
#   ./ui/test_backend.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # ui/
REPO="$(dirname "$HERE")"
OWNER="${DB2_INSTANCE_OWNER:-db2inst1}"

STAGE=/tmp/hybrid-uitest
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp "$HERE/api.py" "$HERE/build_fixtures.py" "$HERE/demo_view.py" "$REPO/tests/test_backend.py" \
   "$HERE/queries.json" "$HERE/demo_queries.json" "$STAGE/"
cp -r "$REPO/src/hybrid_search" "$STAGE/"       # the search engine package
cp -r "$HERE/static" "$STAGE/static"           # api.py mounts static/ at import
chmod -R a+rX "$STAGE"

# fastapi/ibm_db live in the repo venv, not the system python.
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
sudo -iu "$OWNER" bash -lc "cd '$STAGE' && DB2_HOST=local '$PY' test_backend.py"
