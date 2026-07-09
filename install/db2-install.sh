#!/usr/bin/env bash
# db2-install.sh — install Db2, create the db2inst1 instance + SAMPLE database,
# enable Db2 Text Search + register OpenSearch, then leave Db2 STOPPED.
# Scripts the steps in install/README.md (+ the former 3_enable_text_search.sql).
#
# RUN AS ROOT, with the install media already extracted:
#   sudo ./install/db2-install.sh /path/to/server_dec     # dir containing db2_install
#
# Caveats (Db2 install is inherently multi-context and media-specific):
#   - `db2_install` may be interactive or need a response file on your media.
#   - Adjust V12.1 / port / instance via the vars below if yours differ.
#   - Run opensearch-install.sh first (OpenSearch registration is catalog metadata,
#     so OpenSearch need only be installed here, not running).
set -euo pipefail

MEDIA="${1:?Usage: sudo ./install/db2-install.sh /path/to/server_dec}"
INSTANCE="${DB2_INSTANCE:-db2inst1}"
DB2_DIR="${DB2_INSTALL_DIR:-/opt/ibm/db2/V12.1}"
PORT="${DB2_PORT:-50000}"

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
[ -x "$MEDIA/db2_install" ] || { echo "No db2_install in $MEDIA" >&2; exit 1; }

# Root: install binaries, create the instance owner + instance.
"$MEDIA/db2_install"                                         # accept defaults
id "$INSTANCE" &>/dev/null || useradd "$INSTANCE"
echo "Set a password for $INSTANCE:"; passwd "$INSTANCE"
"$DB2_DIR/instance/db2icrt" -u "$INSTANCE" -nosharedgroup "$INSTANCE"

# Text-search setup: enable Db2 Text Search and register OpenSearch as the backend.
TS_SQL="$(mktemp /tmp/enable-text-search.XXXX.sql)"
cat > "$TS_SQL" <<'SQL'
CONNECT TO SAMPLE;
CREATE TABLESPACE systoolspace;
CALL SYSPROC.SYSTS_ENABLE('en_US', ?);
CALL SYSPROC.SYSTS_CREATE_SERVER('localhost', 9200, 'dummyuser:dummypassword', 'dummymasterkey2024', 'OPENSEARCH', 0, 2, 0, 'en_US', ?, ?);
SELECT SERVERID, CAST(HOST AS VARCHAR(40)) AS HOST, PORT
  FROM SYSIBMTS.TSSERVERS WHERE ENGINETYPE='OPENSEARCH';
CONNECT RESET;
SQL
chmod 644 "$TS_SQL"

# As the instance owner: TCP listener + port, build SAMPLE, enable text search, STOP.
# (No `set -e` here so db2stop always runs and Db2 is left stopped.)
su - "$INSTANCE" -c "
  db2set DB2COMM=TCPIP
  db2 update dbm cfg using SVCENAME $PORT
  db2start
  db2sampl
  db2 -tvf '$TS_SQL'
  db2stop
"
rm -f "$TS_SQL"
echo "OK — Db2 installed, instance '$INSTANCE' created, SAMPLE built, Text Search enabled + OpenSearch registered (Db2 now stopped)."
