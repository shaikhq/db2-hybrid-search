# llama.cpp setup — install & download the embedding model

This project generates embeddings **locally**: [llama.cpp](https://github.com/ggml-org/llama.cpp)
serves `BAAI/bge-small-en-v1.5` (384-dim) on an OpenAI-compatible endpoint, and
Db2's `TO_EMBEDDING` calls it during ingest and search. No API keys, no network
egress, no per-call cost.

This page covers **installing llama.cpp and downloading the model** — a one-time
prerequisite. For how Db2 is wired to the running server (the `CREATE EXTERNAL
MODEL` registration, pooling, query prefix, tuning), see
[local-embeddings.md](local-embeddings.md).

> After this one-time setup, the numbered pipeline begins at
> `0_start-services.sh` (which starts the server) → `1_ingest.sql` → `2_search.sql`.

## Automated

`scripts/install/llamacpp-install.sh` runs everything on this page —
build, download, verify (384-dim), then stop the server. Run it for the default
setup, or follow the manual steps below.

## What you end up with

```
~/llama.cpp/build/bin/llama-server                         # the built CPU server
~/models/bge-small-en-v1.5/bge-small-en-v1.5-q8_0.gguf     # the model (~37 MB, q8_0)
```

Serving them yields a 384-dim embedding endpoint at
`http://127.0.0.1:8085/v1/embeddings` (port set by `0_start-services.sh`).

## Manual installation

Three steps — build llama.cpp, download the model, verify. Prerequisites: `git`,
`cmake`, and a C/C++ toolchain.

### 1. Build llama.cpp (CPU)

```bash
# prerequisites: git, cmake, a C/C++ toolchain
#   RHEL/Fedora:  sudo dnf install -y git cmake gcc-c++
#   Debian/Ubuntu: sudo apt-get install -y git cmake build-essential

git clone --depth 1 https://github.com/ggml-org/llama.cpp.git ~/llama.cpp
cmake -S ~/llama.cpp -B ~/llama.cpp/build \
      -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DGGML_NATIVE=ON
cmake --build ~/llama.cpp/build --target llama-server -j"$(nproc)"
```

This builds only `llama-server` (the piece the pipeline needs). The binary lands
at `~/llama.cpp/build/bin/llama-server`.

### 2. Download the model (bge-small-en-v1.5, GGUF)

```bash
mkdir -p ~/models/bge-small-en-v1.5
curl -fSL -o ~/models/bge-small-en-v1.5/bge-small-en-v1.5-q8_0.gguf \
  "https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/bge-small-en-v1.5-q8_0.gguf"
```

`q8_0` is a good accuracy/size trade-off (~37 MB) for this 384-dim model. No
Python or `huggingface-cli` needed — it's a direct download.

### 3. Verify (384-dim)

Bring the server up on a throwaway port, embed once, and check the dimension:

```bash
~/llama.cpp/build/bin/llama-server \
  -m ~/models/bge-small-en-v1.5/bge-small-en-v1.5-q8_0.gguf \
  --embedding --pooling cls --ctx-size 512 --host 127.0.0.1 --port 8099 &
PID=$!
until curl -s -o /dev/null http://127.0.0.1:8099/health; do sleep 1; done
curl -s http://127.0.0.1:8099/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"input":"hello","model":"bge-small-en-v1.5"}' \
  | python3 -c "import sys,json;print('dim', len(json.load(sys.stdin)['data'][0]['embedding']))"
kill "$PID"
# -> dim 384
```

`--pooling cls` is **required** — bge uses CLS pooling, and the wrong pooling
silently degrades retrieval quality.

## Running it for the pipeline

Don't leave the verify server running. The pipeline starts (and stops) the
embedding server for you:

```bash
./scripts/0_start-services.sh        # starts Db2, OpenSearch, and the embedding server (:8085)
./scripts/3_stop-services.sh           # stops them
```

The server must be up for **both** ingest (embedding every row) and search
(embedding each query). Env overrides: `LLAMA_CPP_DIR`, `BGE_GGUF`, `EMBED_PORT`.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `cmake: command not found` | Install it (`dnf install -y cmake` / `apt-get install -y cmake`). |
| Build fails on missing compiler | Install a C/C++ toolchain (`gcc-c++` / `build-essential`). |
| Verify prints a dim other than 384 | Wrong model file, or missing `--pooling cls`. Re-download the GGUF and pass the flag. |
| `TO_EMBEDDING` errors during ingest/search | The server isn't up on `:8085` — run `0_start-services.sh`; smoke-test with the curl above. |
| Download is slow / interrupted | `curl -fSL` resumes poorly; delete the partial `.gguf` and retry, or add `-C -`. |
