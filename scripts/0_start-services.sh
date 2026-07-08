#!/usr/bin/env bash
# 0_start-services.sh — start the three services the pipeline needs: Db2, OpenSearch,
# and the llama.cpp embedding server. Run as the Db2 instance owner. Idempotent:
# skips anything already up. Complete the one-time setup (see docs/) beforehand.
set -uo pipefail

LLAMA="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
MODEL="${BGE_GGUF:-$HOME/models/bge-small-en-v1.5/bge-small-en-v1.5-q8_0.gguf}"
EMBED_PORT="${EMBED_PORT:-8085}"
OS_HOME="${OPENSEARCH_HOME:-/opt/opensearch}"
OS_PORT="${OPENSEARCH_PORT:-9200}"

# Db2
if db2gcf -s 2>/dev/null | grep -q Available; then
  echo "Db2: already running"
else
  db2start && echo "Db2: started"
fi

# OpenSearch
if curl -s -o /dev/null "http://localhost:${OS_PORT}"; then
  echo "OpenSearch: already running on :${OS_PORT}"
else
  sudo -u opensearch "$OS_HOME/bin/opensearch" -d -p "$OS_HOME/opensearch.pid"
  echo "OpenSearch: starting on :${OS_PORT} (~1 min to be ready)"
fi

# llama.cpp embedding server
if curl -s -o /dev/null "http://127.0.0.1:${EMBED_PORT}/health"; then
  echo "Embeddings: already running on :${EMBED_PORT}"
else
  nohup "$LLAMA/build/bin/llama-server" -m "$MODEL" --embedding --pooling cls \
    --ctx-size 512 --host 127.0.0.1 --port "$EMBED_PORT" >/tmp/llama-server.log 2>&1 &
  echo "Embeddings: starting on :${EMBED_PORT} (log: /tmp/llama-server.log)"
fi
