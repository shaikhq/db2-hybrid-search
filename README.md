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
  watsonx.ai model) for the semantic index.

No external vector database, no separate search service to keep in sync — one
Db2 table is the source of truth.

## Architecture: one chunk, two representations

```
PDF ──Docling──▶ Markdown ──HybridChunker──▶ chunks
                                               │
                                               ▼
                         Db2 table  (chunk_id, chunk_text, embedding)
                                ├── chunk_text → Db2 Text Search index (OpenSearch)   → BM25 / CONTAINS · SCORE
                                └── embedding  → native VECTOR column (watsonx.ai)      → cosine · VECTOR_DISTANCE
                                               │
                                               ▼
            6_search.py: run both legs, fuse with RRF — all in one Db2 SQL query
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
- **watsonx.ai** access: an API key, a project id, and an embedding model
  (default: `sentence-transformers/all-minilm-l6-v2`, 384-dim).
- A system library for Docling's OpenCV dependency (`libGL.so.1`):
  - RHEL/Fedora: `sudo dnf install -y libglvnd-glx`
  - Debian/Ubuntu: `sudo apt-get install -y libgl1`

> Run the pipeline **as the Db2 instance owner** (e.g. `db2inst1`). The cleanup
> and text-index steps use the `db2ts` command-line tool, which must run locally
> as the instance owner.

## Setup

```bash
# 1. Clone
git clone <your-repo-url> hybrid-search
cd hybrid-search

# 2. Create a virtual environment and install dependencies.
python3 -m venv .venv
source .venv/bin/activate

# CPU-only PyTorch first (avoids large CUDA downloads):
pip install --index-url https://download.pytorch.org/whl/cpu torch==2.12.1 torchvision==0.27.1
pip install -r requirements.txt

# 3. Configure credentials. Copy the template and fill in real values.
cp .env.example .env
$EDITOR .env          # Db2 connection + watsonx.ai API key / project id
```

`.env` is git-ignored — your real credentials are never committed.

## Usage — run the scripts in order

The filenames are numbered by execution order — run them **1 → 6** as the Db2
instance owner, from the repo root. The ingestion is split into small steps
(extract → chunk → load) so you can open and inspect each intermediate file:
the `.md` and the `.chunks.csv`.

### 1. `1_cleanup.sh` — clean slate

```bash
./scripts/1_cleanup.sh
```

Drops the text-search index, then the chunks table (in that dependency order).
Idempotent — safe to run even if nothing exists yet.
**Leaves behind:** an empty schema, ready for a fresh ingest.

### 2. `2_setup.sh` — one-time setup

```bash
./scripts/2_setup.sh
```

Enables Db2 Text Search and registers OpenSearch as the lexical backend.
Only needs to succeed once per database; safe to re-run.

### 3. `3_extract.py` — PDF → Markdown

```bash
python scripts/3_extract.py path/to/your-document.pdf
```

Docling parses the PDF and writes clean Markdown next to it (`your-document.md`).
**Leaves behind:** a Markdown file you can open and read.

### 4. `4_chunk.py` — Markdown → chunks (CSV)

```bash
python scripts/4_chunk.py path/to/your-document.md
```

Splits the Markdown with Docling's HybridChunker (capped to the embedding
model's token limit) and writes a two-column CSV (`chunk_id, chunk_text`).
**Leaves behind:** `your-document.chunks.csv` — open it to see exactly what gets indexed.

### 5. `5_ingest.py` — chunks (CSV) → Db2

```bash
python scripts/5_ingest.py path/to/your-document.chunks.csv
```

Loads the chunks into a Db2 table, builds the Db2 Text Search lexical index,
registers the watsonx.ai embedding model, and fills a `VECTOR` column with
in-database embeddings.
**Leaves behind:** one table (default `myschema.chunks`) where every row has
`chunk_id`, `chunk_text`, a text-search index entry, and an `embedding` vector.

> Lexical-only (no watsonx): set `SKIP_EMBEDDING=1` in `.env` to stop after the
> text index.

### 6. `search.sh` — hybrid retrieval

```bash
./scripts/search.sh                                       # preset demo queries
./scripts/search.sh "how do I turn text into vectors"     # your own query
```

`search.sh` runs the search over a **fast local Db2 connection** (as the instance
owner) — handy when the `ibm_db` TCP connect is slow. It's a thin wrapper around
`6_search.py`, which you can also run directly if your `.env` points at a Db2 you
reach over TCP: `python scripts/6_search.py "..."`.

For each query it runs the **lexical** leg (`CONTAINS` + BM25 `SCORE`) and the
**vector** leg (`VECTOR_DISTANCE` over a freshly embedded query), then **fuses
them in one Db2 SQL query**. It prints all three rankings — with each result's
score — so you can see lexical nail exact terms, vector catch paraphrases, and
the fusion get both. With no argument it runs a couple of preset queries; with an
argument it searches that query.
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

### Measuring quality — `eval.sh`

```bash
./scripts/eval.sh
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

# 2. Start the demo (offline — no Db2/watsonx needed at talk time)
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
hybrid.** Run any of them with:

```bash
./scripts/search.sh "what privilege do I need to call TO_EMBEDDING"
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

Everything is configured via `.env`: Db2 connection, watsonx.ai credentials,
schema/table names, chunk token cap, and vector dimension. The fusion knobs
(`HYBRID_W_LEX`, `HYBRID_W_VEC`, `HYBRID_VEC_GATE`, `HYBRID_LEX_GATE`,
`HYBRID_POOL`) are optional — tune them against `./scripts/eval.sh`. See
[.env.example](.env.example).

## Repository layout

```
scripts/   1_cleanup.sh · 2_setup.sh · 3_extract.py · 4_chunk.py · 5_ingest.py · 6_search.py
           search.sh (fast local search) · eval.sh (quality metrics)
           hybrid_core.py (search engine + fusion) · eval.py (golden set)
ui/        run.sh · build_fixtures.sh · api.py · queries.json · static/ (the demo)
docs/      Db2 and OpenSearch setup notes, images
```

## Docs

- [docs/setup-and-run.md](docs/setup-and-run.md) — full end-to-end setup & run runbook (with real-VM gotchas).
- [docs/db2-setup.md](docs/db2-setup.md) — install and prepare Db2 12.1.5.
- [docs/opensearch-setup.md](docs/opensearch-setup.md) — install OpenSearch and wire it to Db2 Text Search.
- [docs/eval-results.md](docs/eval-results.md) — search-quality evaluation results from `./scripts/eval.sh`.
- [ui/README.md](ui/README.md) — the demo UI: one-command run, acceptance walk-through, design notes.

## License

[Apache-2.0](LICENSE).
