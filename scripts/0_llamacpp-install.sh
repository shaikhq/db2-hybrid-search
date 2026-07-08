#!/usr/bin/env bash
# 0_llamacpp-install.sh — build llama.cpp and download bge-small-en-v1.5, then verify
# it serves 384-dim embeddings. Does NOT leave a server running (1_start-services.sh
# does that). One-time. Idempotent: skips build/download if already present.
set -euo pipefail

LLAMA="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
MODEL_DIR="${BGE_DIR:-$HOME/models/bge-small-en-v1.5}"
MODEL="$MODEL_DIR/bge-small-en-v1.5-q8_0.gguf"

command -v cmake >/dev/null || sudo dnf install -y cmake

# Build llama-server (CPU).
if [ ! -x "$LLAMA/build/bin/llama-server" ]; then
  [ -d "$LLAMA/.git" ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA"
  cmake -S "$LLAMA" -B "$LLAMA/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DGGML_NATIVE=ON
  cmake --build "$LLAMA/build" --target llama-server -j"$(nproc)"
fi

# Download the GGUF (direct, no Python deps).
if [ ! -f "$MODEL" ]; then
  mkdir -p "$MODEL_DIR"
  curl -fSL -o "$MODEL" \
    "https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/bge-small-en-v1.5-q8_0.gguf"
fi

# Verify: bring a server up on a throwaway port, embed once, then stop it.
echo "Verifying embeddings…"
"$LLAMA/build/bin/llama-server" -m "$MODEL" --embedding --pooling cls --ctx-size 512 \
  --host 127.0.0.1 --port 8099 >/tmp/llamacpp-verify.log 2>&1 &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' EXIT
until curl -s -o /dev/null http://127.0.0.1:8099/health; do sleep 1; done
DIM=$(curl -s http://127.0.0.1:8099/v1/embeddings -H 'Content-Type: application/json' \
        -d '{"input":"hello","model":"bge-small-en-v1.5"}' \
      | python3 -c "import sys,json;print(len(json.load(sys.stdin)['data'][0]['embedding']))")
kill "$PID" 2>/dev/null || true; trap - EXIT

[ "$DIM" = "384" ] \
  && echo "OK — llama.cpp + bge-small serve 384-dim embeddings (server left stopped)." \
  || { echo "FAILED — expected dim 384, got '$DIM' (see /tmp/llamacpp-verify.log)"; exit 1; }
