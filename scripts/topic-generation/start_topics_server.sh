#!/usr/bin/env bash
# Topic-generation server: proposes candidate QUERIES for building a test collection.
# Reuses the same Qwen GGUF as the query-understanding server but runs as a SEPARATE
# instance, for two reasons:
#
#   1. the grammar is bound at server start, and :8086 already loads qu_gen.gbnf;
#   2. :8086 runs --temp 0 --top-k 1, correct for a reproducible routing gate and wrong
#      here — greedy decoding returns ten rephrasings of the same two ideas, when the
#      entire point of this server is variety.
#
# Sampling lives on the CLIENT (hybrid_search/topicgen.py sends temperature/top_p per
# request), so no --temp is set here; only the grammar and context are server-bound.
#
# Start:  ./scripts/topic-generation/start_topics_server.sh
# Stop:   fuser -k 8088/tcp
set -uo pipefail
LLAMA="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
# Same model file as the QU server by default — no second download.
MODEL="${TOPICS_GGUF:-${QU_GGUF:-$HOME/models/qwen2.5-3b-instruct/Qwen2.5-3B-Instruct-Q4_K_M.gguf}}"
PORT="${TOPICS_PORT:-8088}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if curl -s -o /dev/null "http://127.0.0.1:${PORT}/health"; then
  echo "topics server: already running on :${PORT}"; exit 0
fi
if [ ! -f "$MODEL" ]; then
  echo "topics server: model not found at $MODEL" >&2
  echo "  set TOPICS_GGUF (or QU_GGUF) to a chat-instruct GGUF." >&2
  exit 1
fi

# Bigger --ctx-size and --n-predict than the QU server: that one emits a single short
# rewrite, this one emits a list of up to 40 queries in one response.
nohup "$LLAMA/build/bin/llama-server" -m "$MODEL" \
  --host 127.0.0.1 --port "$PORT" --ctx-size 4096 --n-predict 1024 \
  --alias "${TOPICS_MODEL:-topics}" \
  --grammar-file "$HERE/topics.gbnf" \
  --parallel 1 >/tmp/topics-server.log 2>&1 &

echo "topics server: starting on :${PORT} (log: /tmp/topics-server.log; ~20s to load)"
echo "  the Label tab's 'Generate topics' needs this running."
