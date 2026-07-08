# Hybrid Search on IBM Db2 12.1.5

Build a **hybrid search** corpus inside Db2 — keyword search *and* semantic
(vector) search over the same data — straight from a PDF.

## What this does / why it exists

Most "AI search" demos do only half the job. Real-world retrieval works best
when you combine **two** ways of finding text:

- **Lexical** (keyword / BM25) — great at exact terms: API names, error codes, identifiers.
- **Semantic** (vector embeddings) — great at meaning: paraphrases and synonyms.

This project ingests a PDF and stores each chunk in Db2 with **both**
representations, then searches with both and fuses the results. It uses
Db2 12.1.5's built-in features end to end:

- **Db2 Text Search** (OpenSearch-backed) for the lexical/BM25 index, and
- **native `VECTOR` columns + in-database `TO_EMBEDDING`** (via a registered
  OpenAI-compatible model — local llama.cpp `bge-small-en-v1.5`) for the semantic index.

No external vector database, no separate search service to keep in sync — one
Db2 table is the source of truth.

## Architecture: one chunk, two representations

```
PDF ──Docling──▶ Markdown ──HybridChunker──▶ chunks
                                               │
                                               ▼
                         Db2 table  (chunk_id, chunk_text, embedding)
                                ├── chunk_text → Db2 Text Search index (OpenSearch)   → BM25 / CONTAINS · SCORE
                                └── embedding  → native VECTOR column (local bge-small)  → cosine · VECTOR_DISTANCE
                                               │
                                               ▼
            5_search.sql: run both legs, fuse — all in one Db2 SQL query
```

Each chunk is **one row** holding its text, a stable `chunk_id`, a text-search
index entry, and its dense vector. Search runs the keyword leg and the vector
leg, then **RRF** merges the two rankings into one — so each leg covers the
other's blind spot.

## Prerequisites

- **IBM Db2 12.1.5** with the native `VECTOR` type and in-database embedding
  (model registration + `TO_EMBEDDING`). See [docs/db2-setup.md](docs/db2-setup.md).
- **OpenSearch**, installed and registered with Db2 Text Search.
  See [docs/opensearch-setup.md](docs/opensearch-setup.md).
- **Python 3.12** and the packages in [requirements.txt](requirements.txt).
- A **local embedding server** — llama.cpp serving `BAAI/bge-small-en-v1.5`
  (384-dim) on an OpenAI-compatible endpoint. Db2's `PROVIDER OPENAI` model calls
  it; no API keys, no network egress. See [docs/local-embeddings.md](docs/local-embeddings.md).
- A system library for Docling's OpenCV dependency (`libGL.so.1`):
  - RHEL/Fedora: `sudo dnf install -y libglvnd-glx`
  - Debian/Ubuntu: `sudo apt-get install -y libgl1`

> Run the pipeline **as the Db2 instance owner** (e.g. `db2inst1`). The SQL
> scripts' text-search admin steps must run on a local Db2 connection as the
> instance owner.

## Setup (one-time)

```bash
git clone <your-repo-url> hybrid-search && cd hybrid-search
```

Install the pieces — each is idempotent and leaves nothing running:

```bash
./scripts/0_docling-install.sh      # Python venv: Docling, ibm_db, UI deps (+ libGL)
./scripts/0_llamacpp-install.sh     # build llama.cpp + download bge-small-en-v1.5, verify
./scripts/0_opensearch-install.sh   # install + configure OpenSearch (Db2 Text Search backend)
sudo ./scripts/0_db2-install.sh /path/to/server_dec   # install Db2 + instance + SAMPLE (skip if Db2 exists)
```

Then configure the connection:

```bash
cp .env.example .env
$EDITOR .env          # Db2 connection + password (embeddings are local — no API keys)
```

`.env` is git-ignored — your real credentials are never committed.

## Usage — run the scripts in order

The filenames are numbered by execution order. **Step 0** is the one-time installs
(see [Setup](#setup-one-time)); then run **1 → 5** as the Db2 instance owner from
the repo root. Step 1 brings up the services; the ingestion (2–4) is split into
small steps (extract → chunk → load) so you can inspect each intermediate file: the
`.md` and the `.chunks.csv`. (Text Search is enabled once by `0_db2-install.sh`.)

### 1. Start the services

The pipeline needs three services up — **Db2**, **OpenSearch**, and the **llama.cpp
embedding server** (Db2's `TO_EMBEDDING` calls it during ingest and search). After
the one-time [Setup](#setup-one-time), bring them all up:

```bash
./scripts/1_start-services.sh        # starts Db2, OpenSearch, and the embedding server
```

Idempotent (skips anything already up). Stop them with `./scripts/stop-services.sh`.

### 2. `2_extract.py` — PDF → Markdown

```bash
python scripts/2_extract.py path/to/your-document.pdf
```

Docling parses the PDF and writes clean Markdown next to it (`your-document.md`).
**Leaves behind:** a Markdown file you can open and read.

### 3. `3_chunk.py` — Markdown → chunks (CSV)

```bash
python scripts/3_chunk.py path/to/your-document.md
```

Splits the Markdown with Docling's HybridChunker (capped to the embedding
model's token limit) and writes a two-column CSV (`chunk_id, chunk_text`).
**Leaves behind:** `your-document.chunks.csv` — open it to see exactly what gets indexed.

### 4. `4_ingest.sql` — chunks (CSV) → Db2

```bash
db2 -tvf scripts/4_ingest.sql
```

Drops any existing chunks table/index (so it's re-runnable), `IMPORT`s
`sample.chunks.csv` into a fresh table, builds the Db2 Text Search index
(`SYSTS_CREATE`/`SYSTS_UPDATE`), registers the local embedding model
(`PROVIDER OPENAI` → llama.cpp), fills a `VECTOR` column via `TO_EMBEDDING`, and
builds the vector index.

Before the first run: `db2set DB2_VECTOR_INDEXING=YES -immediate` (once), and make
sure the services from step 1 are up (`./scripts/1_start-services.sh`) so
`TO_EMBEDDING` can reach the embedding server. No secrets — it's local and keyless.
See [docs/local-embeddings.md](docs/local-embeddings.md).
**Leaves behind:** one table (default `myschema.chunks`) where every row has
`chunk_id`, `chunk_text`, a text-search index entry, and an `embedding` vector.

> Lexical-only: delete the model / embed / vector-index sections in
> `4_ingest.sql` (keep table + text index).
> The script reads a fixed filename, `sample.chunks.csv`; rename your CSV to that
> or edit the `IMPORT FROM` line.

### 5. `5_search.sql` — hybrid retrieval

```bash
db2 -tvf scripts/5_search.sql
```

Runs all three legs for **one hardcoded query** and prints them: the **lexical**
leg (`CONTAINS` + BM25 `SCORE`), the **vector** leg (`VECTOR_DISTANCE` over the
query embedding), and the **hybrid** fusion — the gated, score-normalized weighted
sum, **all in one Db2 SQL query**. To search something else, edit the query text
in the three statements (the raw form for the vector leg and the `word OR word …`
form for the keyword leg). For dynamic ad-hoc queries, use the live demo UI, which
calls the same engine (`hybrid_core.py`).
**Leaves behind:** nothing — it's read-only.

**How the fusion works (and why not plain RRF).** Reciprocal Rank Fusion ranks
by position only, so a leg that is essentially guessing (vectors on an exact
error code, keywords on a pure paraphrase) injects its top guesses with the same
weight as the other leg's real hits — and they tie, so noise floats to the top.
Instead, the fusion (in [scripts/hybrid_core.py](scripts/hybrid_core.py)):
1. carries each leg's real score (BM25 `SCORE`, cosine similarity),
2. **gates** a leg out when its best score is below a threshold (a near-random
   leg contributes nothing — e.g. vectors whose top cosine similarity `< 0.30`),
3. **max-normalizes** the survivors to `(0,1]`, and
4. takes a **weighted sum**.
A document found by *both* legs is reinforced; a noisy leg is muted. The gates,
weights, and candidate-pool size are `.env`-tunable (`HYBRID_*`).

### Measuring quality — `eval.py`

```bash
DB2_HOST=local python scripts/eval.py
```

Runs a small golden set (query → known-relevant chunks, in
[scripts/eval.py](scripts/eval.py)) and reports **MRR, Recall@5, and Hits@1** for
each leg and the fusion, plus a per-query table of where the first relevant
result landed. Run it after any change to chunking, the embedding model, or the
fusion knobs and judge the change by the numbers rather than by eyeballing one
query. On the sample corpus the fusion beats both legs on every metric (e.g.
hybrid MRR ≈ 0.89 vs vector 0.68 vs lexical 0.51).

## Demo UI

A minimalist web demo that shows, in a few clicks, how each single retriever has a
blind spot and hybrid covers both — side by side, with the gold answer's rank
highlighted.

```bash
# 1. Freeze results for the curated queries (runs the real search once)
./ui/build_fixtures.sh

# 2. Start the demo (offline — no Db2, no embedding server needed)
./ui/run.sh                 # → http://127.0.0.1:8000

# Optional: ad-hoc typed queries against the live engine
./ui/run.sh --live          # FastAPI backend; Swagger at /docs
```

The default run serves a static page + frozen `fixtures.json` with Python's
stdlib server, so the talk runs fully offline. See [ui/README.md](ui/README.md)
for the layout, the acceptance walk-through, and color/design notes.

## Example queries to try

These are written for the IBM Db2 12.1.5 LLM-integration reference PDF this project
was built around — adapt them to your own document. The principle is general:
**exact terms favor keyword search, paraphrases favor vectors, and a mix favors
hybrid.** To try one, put it into the query text in `scripts/5_search.sql`
(both the raw and `word OR word …` forms), then:

```bash
db2 -tvf scripts/5_search.sql
```

**Keyword search wins** — an exact **SQLSTATE error code** is just digits with no
meaning to embed, so the vector leg scatters to unrelated chunks while keyword
search lands the exact rule that raises it:
- `42615` → the option value-range checks (`TEMPERATURE`, `FREQUENCY_PENALTY`, …) that raise this code
- `42613` → the `ALTER EXTERNAL MODEL` rule about setting and dropping a parameter in one statement

**Vector search wins** — plain-language questions whose words don't appear in the
answer; the keyword leg misses but the embedding finds the right chunk:
- `how can I make the model stop generating at a certain phrase` → the **STOP_SEQUENCE** option
- `how do I turn text into vectors` → the **TEXT_EMBEDDING** model type

**Hybrid wins** — a distinctive term *and* natural phrasing, where both legs
contribute to the fused ranking:
- `what privilege do I need to call TO_EMBEDDING` → the **USAGE** privilege
- `how do I change the API key on an existing model` → **ALTER EXTERNAL MODEL … SET KEY**

## Configuration

Everything is configured via `.env`: Db2 connection, schema/table names, chunk
token cap, and vector dimension. (Embeddings are local — no API keys; the
embedding model/endpoint is set in `4_ingest.sql`.) The fusion knobs
(`HYBRID_W_LEX`, `HYBRID_W_VEC`, `HYBRID_VEC_GATE`, `HYBRID_LEX_GATE`,
`HYBRID_POOL`) are optional — tune them against `eval.py`. See
[.env.example](.env.example).

## Repository layout

```
scripts/   install:   0_docling-install.sh · 0_llamacpp-install.sh · 0_opensearch-install.sh · 0_db2-install.sh
           services:  1_start-services.sh · stop-services.sh
           pipeline:  2_extract.py · 3_chunk.py · 4_ingest.sql · 5_search.sql
           other:     hybrid_core.py (engine+fusion, used by eval.py + UI) · eval.py · pipeline-2-5.sh
ui/        run.sh · build_fixtures.sh · api.py · queries.json · static/ (the demo)
docs/      Db2, OpenSearch, and local-embeddings setup notes
```

## Docs

- [docs/setup-and-run.md](docs/setup-and-run.md) — full end-to-end setup & run runbook (with real-VM gotchas).
- [docs/db2-setup.md](docs/db2-setup.md) — install and prepare Db2 12.1.5.
- [docs/opensearch-setup.md](docs/opensearch-setup.md) — install OpenSearch and wire it to Db2 Text Search.
- [docs/local-embeddings.md](docs/local-embeddings.md) — serve bge-small-en-v1.5 locally via llama.cpp for `TO_EMBEDDING`.
- [docs/eval-results.md](docs/eval-results.md) — search-quality evaluation results from `eval.py`.
- [ui/README.md](ui/README.md) — the demo UI: one-command run, acceptance walk-through, design notes.

## License

[Apache-2.0](LICENSE).
