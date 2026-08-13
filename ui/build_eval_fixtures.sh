#!/usr/bin/env bash
# Freeze the Evaluate tab's numbers for the offline demo. Run as the Db2 instance owner.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
cd "$REPO"
EVAL_SETS_DIR="$REPO/data/eval/sets" DB2_HOST=local PYTHONPATH="$REPO/src" "$PY" "$HERE/build_eval_fixtures.py"
