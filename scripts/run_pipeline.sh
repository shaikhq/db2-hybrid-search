#!/usr/bin/env bash
# run_pipeline.sh — run the whole ingestion pipeline (steps 1-4) on one PDF.
#
#   ./scripts/run_pipeline.sh path/to/document.pdf
#
# Runs, in order:
#   1_extract.py   (as you)        PDF       -> document.md
#   2_chunk.py     (as you)        document.md -> document.chunks.csv
#   3_enable_text_search.sql    (as db2inst1)   enable text search + register OpenSearch
#   4_ingest.sql   (as db2inst1)   cleanup + sample.chunks.csv -> Db2  (embedding server must be up)
#
# Run from the repo root as your normal user. The two shell steps are piped to
# db2inst1 via sudo (so db2/db2ts are available); the Python steps use the
# project's .venv. Search (step 5) is separate: ./scripts/search.sh.

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: ./scripts/run_pipeline.sh path/to/document.pdf" >&2
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
"$PY" "$SCRIPTS/1_extract.py" "$PDF"

echo "### 2/4  chunk    $MD -> $CSV"
"$PY" "$SCRIPTS/2_chunk.py" "$MD"

echo "### 3/4  setup    (as $OWNER)"
sudo -iu "$OWNER" bash -lc 'db2 -tv' < "$SCRIPTS/3_enable_text_search.sql"

echo "### 4/4  ingest   cleanup + sample.chunks.csv -> Db2  (as $OWNER)"
# NOTE: 4_ingest.sql clears any old table/index, then reads the FIXED file
# sample.chunks.csv. The local embedding server (scripts/serve_embeddings.sh)
# must already be running, or the embedding step fails.
sudo -iu "$OWNER" bash -lc "db2set DB2_VECTOR_INDEXING=YES -immediate; cd '$REPO' && db2 -tv" < "$SCRIPTS/4_ingest.sql"

echo "### done — corpus is ready. Search it with:  ./scripts/search.sh"
