#!/usr/bin/env bash
# serve_embeddings.sh — serve BAAI/bge-small-en-v1.5 as a local OpenAI-compatible
# embeddings endpoint (llama.cpp), for Db2's in-database TO_EMBEDDING.
#
# Db2's PROVIDER OPENAI model (registered in 4_ingest.sql) calls
#   http://127.0.0.1:8085/v1/embeddings
# Start this BEFORE 4_ingest.sql and keep it running for search (the vector leg
# embeds each query the same way). See docs/local-embeddings.md for setup.
set -euo pipefail
LLAMA="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
MODEL="${BGE_GGUF:-$HOME/models/bge-small-en-v1.5/bge-small-en-v1.5-q8_0.gguf}"
PORT="${EMBED_PORT:-8085}"
exec "$LLAMA/build/bin/llama-server" -m "$MODEL" \
  --embedding --pooling cls --ctx-size 512 \
  --host 127.0.0.1 --port "$PORT"
