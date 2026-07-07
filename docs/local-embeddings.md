# Local embeddings with llama.cpp (bge-small-en-v1.5)

The pipeline generates embeddings **in-database** via Db2's `TO_EMBEDDING`, which
calls an external model registered with `CREATE EXTERNAL MODEL`. Instead of
watsonx.ai, this project points that model at a **local** OpenAI-compatible
endpoint served by [llama.cpp](https://github.com/ggml-org/llama.cpp) running
`BAAI/bge-small-en-v1.5` (384-dim). No API keys, no network egress, no per-call
cost — and the same `VECTOR(384)` schema as before.

Db2 supports this because `CREATE EXTERNAL MODEL … PROVIDER OPENAI` accepts any
REST endpoint compatible with the OpenAI API spec (see the Db2 12.1.5 reference).
A plain `http://` localhost URL works — no TLS proxy required.

```
Db2  TO_EMBEDDING(text USING MYSCHEMA.CHUNKS_EMBED)
      │  PROVIDER OPENAI, URL http://127.0.0.1:8085/v1/embeddings
      ▼
llama-server  (bge-small-en-v1.5, --embedding --pooling cls)  →  384-dim vector
```

## One-time setup

**1. Build llama.cpp** (needs `cmake`, `gcc`/`g++`):

```bash
sudo dnf install -y cmake                      # if missing
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git ~/llama.cpp
cd ~/llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DGGML_NATIVE=ON
cmake --build build --target llama-server -j"$(nproc)"
```

**2. Download the GGUF** (~37 MB, q8_0):

```bash
python - <<'PY'
from huggingface_hub import hf_hub_download
hf_hub_download("CompendiumLabs/bge-small-en-v1.5-gguf",
               "bge-small-en-v1.5-q8_0.gguf",
               local_dir="$HOME/models/bge-small-en-v1.5")
PY
```

## Run the embedding server

```bash
./scripts/serve_embeddings.sh          # serves on http://127.0.0.1:8085
```

Overridable via env: `LLAMA_CPP_DIR`, `BGE_GGUF`, `EMBED_PORT`. Keep it running —
it's used **both** at ingest time (embedding every chunk) and at search time
(embedding each query, via `hybrid_core.py`'s vector leg).

Smoke test:

```bash
curl -s http://127.0.0.1:8085/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"input":"hello","model":"bge-small-en-v1.5"}' \
  | python3 -c "import sys,json;print('dim',len(json.load(sys.stdin)['data'][0]['embedding']))"
# -> dim 384
```

## How Db2 is wired to it

`4_ingest.sql` registers the model:

```sql
CREATE EXTERNAL MODEL MYSCHEMA.CHUNKS_EMBED PROVIDER OPENAI
  ID 'bge-small-en-v1.5'
  URL 'http://127.0.0.1:8085/v1/embeddings'
  TYPE TEXT_EMBEDDING RETURNING VECTOR(384, FLOAT32)
  KEY 'sk-noauth';          -- dummy: the local server has no auth (KEY can't be empty)
```

`PROVIDER OPENAI` takes **no** `PROJECT_ID`. Everything downstream is unchanged:
`UPDATE … SET embedding = TO_EMBEDDING(...)` fills the vectors, and the vector
search leg embeds queries through the same model.

## Notes / tuning

- **Pooling**: bge uses CLS pooling → `--pooling cls`. (Wrong pooling silently
  degrades quality.)
- **Query instruction**: bge retrieval is tuned for a query prefix
  ("Represent this sentence for searching relevant passages: "). `TO_EMBEDDING`
  embeds queries and passages identically, so that asymmetry is not applied here
  — a known small quality cost vs. the model's benchmark numbers.
- **Fusion gate**: `HYBRID_VEC_GATE` (default 0.30) was tuned against the previous
  model's cosine distribution. Re-tune it against `eval.py` for bge if you want to
  squeeze back MRR.
- Judge any change by `DB2_HOST=local python scripts/eval.py`, not one query.
