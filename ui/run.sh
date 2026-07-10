#!/usr/bin/env bash
# run.sh — start the demo with ONE command.
#
#   ./ui/run.sh           OFFLINE (default): serves the static UI + frozen
#                         fixtures.json with python's stdlib server. No Db2, no
#                         pip deps — this is the conference/talk path.
#
#   ./ui/run.sh --live    LIVE: FastAPI backend answers typed queries against the
#                         real engine (runs as the Db2 instance owner, local
#                         connection). For Q&A / ad-hoc queries.
#
# Build/refresh the fixtures first with:  ./ui/build_fixtures.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
OWNER="${DB2_INSTANCE_OWNER:-db2inst1}"
PORT="${PORT:-8000}"

if [ "${1:-}" = "--live" ]; then
    # Stage everything the instance owner can read (it can't read /home/<you>).
    STAGE=/tmp/hybrid-ui
    rm -rf "$STAGE"; mkdir -p "$STAGE"
    cp "$HERE/api.py" "$HERE/build_fixtures.py" "$HERE/demo_view.py" \
       "$HERE/queries.json" "$HERE/demo_queries.json" "$STAGE/"
    cp -r "$REPO/src/hybrid_search" "$STAGE/"      # the search engine package
    cp -r "$HERE/static" "$STAGE/static"
    [ -f "$REPO/.env" ] && cp "$REPO/.env" "$STAGE/.env"   # fusion weights/gates/pool
    chmod -R a+rX "$STAGE"
    # uvicorn/fastapi/ibm_db live in the repo venv, not the system python.
    PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
    # A previous server orphaned by a closed terminal keeps holding the port and
    # would block the bind ("address already in use"). It runs as $OWNER, so free
    # the port as $OWNER before starting.
    if sudo -iu "$OWNER" bash -lc "fuser ${PORT}/tcp" >/dev/null 2>&1; then
        echo "Port ${PORT} busy — stopping the previous live server first."
        sudo -iu "$OWNER" bash -lc "fuser -k ${PORT}/tcp" >/dev/null 2>&1 || true
        sleep 1
    fi
    echo "LIVE  → http://127.0.0.1:$PORT   (real Db2 search as $OWNER; docs at /docs)"
    sudo -iu "$OWNER" bash -lc \
        "cd '$STAGE' && DB2_HOST=local '$PY' -m uvicorn api:app --host 127.0.0.1 --port $PORT"
else
    [ -f "$HERE/static/fixtures.json" ] || {
        echo "No fixtures yet — run ./ui/build_fixtures.sh first." >&2; exit 1; }
    # Free the port if a previous offline server (this user) is still holding it.
    if fuser "${PORT}/tcp" >/dev/null 2>&1; then
        echo "Port ${PORT} busy — stopping the previous server first."
        fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
        sleep 1
    fi
    echo "OFFLINE → http://127.0.0.1:$PORT   (frozen fixtures, no Db2 needed)"
    cd "$HERE/static" && exec python3 -m http.server "$PORT" --bind 127.0.0.1
fi
