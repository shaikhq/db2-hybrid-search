#!/usr/bin/env bash
# pipeline-2-5.sh — build and demo on one PDF: extract, chunk, ingest, then search.
#
#   ./scripts/pipeline-2-5.sh path/to/document.pdf
#
# Runs, in order:
#   2_extract.py   (as you)        PDF       -> document.md
#   3_chunk.py     (as you)        document.md -> document.chunks.csv
#   4_ingest.sql   (as db2inst1)   cleanup + sample.chunks.csv -> Db2  (embedding server must be up)
#   5_search.sql   (as db2inst1)   demo query — prints lexical / vector / hybrid results
#
# Run from the repo root as your normal user. Text Search is enabled once by
# 0_db2-install.sh (not here). The Python steps use the project's .venv; the SQL
# steps are piped to db2inst1 via sudo.

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: ./scripts/pipeline-2-5.sh path/to/document.pdf" >&2
    exit 1
fi

PDF="$1"
[ -f "$PDF" ] || { echo "PDF not found: $PDF" >&2; exit 1; }

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # the scripts/ dir
REPO="$(dirname "$SCRIPTS")"                              # repo root
PY="$REPO/.venv/bin/python3"
OWNER="${DB2_INSTANCE_OWNER:-db2inst1}"

# Intermediate files — match each script's default output path.
MD="${PDF%.*}.md"
CSV="${PDF%.*}.chunks.csv"

echo "### 1/4  extract  $PDF -> $MD"
"$PY" "$SCRIPTS/2_extract.py" "$PDF"

echo "### 2/4  chunk    $MD -> $CSV"
"$PY" "$SCRIPTS/3_chunk.py" "$MD"

echo "### 3/4  ingest   cleanup + sample.chunks.csv -> Db2  (as $OWNER)"
# NOTE: 4_ingest.sql clears any old table/index, then reads the FIXED file
# sample.chunks.csv. The local embedding server (scripts/1_start-services.sh)
# must already be running, or the embedding step fails.
sudo -iu "$OWNER" bash -lc "db2set DB2_VECTOR_INDEXING=YES -immediate; cd '$REPO' && db2 -tv" < "$SCRIPTS/4_ingest.sql"

echo "### 4/4  search   demo query  (as $OWNER)"
sudo -iu "$OWNER" bash -lc 'db2 -tv' < "$SCRIPTS/5_search.sql"

echo "### done — corpus built and searched."
