#!/usr/bin/env bash
# search.sh — run the hybrid search demo (scripts/5_search.sql) on a local Db2
# connection. The query is hardcoded in 5_search.sql; edit it there to search
# something else. Run as the Db2 instance owner.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
db2 -tvf "$HERE/5_search.sql"
