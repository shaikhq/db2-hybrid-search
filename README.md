# Hybrid Search on IBM Db2 12.1.5

Build a **hybrid search** corpus inside Db2 — keyword search *and* semantic
(vector) search over the same data — from a CSV corpus you provide.

## What this does / why it exists

Most "AI search" demos do only half the job. Real-world retrieval works best
when you combine **two** ways of finding text:

- **Lexical** (keyword / BM25) — great at exact terms: API names, error codes, identifiers.
- **Semantic** (vector embeddings) — great at meaning: paraphrases and synonyms.

This project ingests a CSV corpus (one text chunk per row) and stores each row in
Db2 with **both** representations, then searches with both and fuses the results.
It uses Db2 12.1.5's built-in features end to end:

- **Db2 Text Search** (OpenSearch-backed) for the lexical/BM25 index, and
- **native `VECTOR` columns + in-database `TO_EMBEDDING`** (via a registered
  OpenAI-compatible model — local llama.cpp `bge-small-en-v1.5`) for the semantic index.

No external vector database, no separate search service to keep in sync — one
Db2 table is the source of truth.

## Architecture: one chunk, two representations

```
CSV corpus (chunk_id, chunk_text)
        │
        ▼
Db2 table  (chunk_id, chunk_text, embedding)
       ├── chunk_text → Db2 Text Search index (OpenSearch)      → BM25 / CONTAINS · SCORE
       └── embedding  → native VECTOR column (local bge-small)  → cosine · VECTOR_DISTANCE
                            │
                            ▼
       2_search.sql: run both legs, fuse — all in one Db2 SQL query
```

Each row holds its text, a stable `chunk_id`, a text-search index entry, and its
dense vector. Search runs the keyword leg and the vector leg, then a **gated,
score-normalized weighted sum** (not plain RRF — see
[Usage §2](#2-2_searchsql--hybrid-retrieval)) fuses the two rankings into one —
so each leg covers the other's blind spot.

## Prerequisites

- **IBM Db2 12.1.5** with the native `VECTOR` type and in-database embedding
  (model registration + `TO_EMBEDDING`).
- **OpenSearch**, installed and registered with Db2 Text Search.
- **Python 3.12**; install the project with `pip install -e .` — pulls in `ibm_db`
  and the live-UI deps from [requirements.txt](requirements.txt).
- A **local embedding server** — llama.cpp serving `BAAI/bge-small-en-v1.5`
  (384-dim) on an OpenAI-compatible endpoint. Db2's `PROVIDER OPENAI` model calls
  it; no API keys, no network egress.

  Full setup for all of the above is in **[install/README.md](install/README.md)**.
- A **corpus CSV** at `data/corpus.csv`. The shipped corpus is a personal audiobook
  library (one row per book; `chunk_text` = title + authors + narrators + description).
  Bring your own by matching that schema, or edit the `IMPORT` in `1_ingest.sql`.

> Run the pipeline **as the Db2 instance owner** (e.g. `db2inst1`). The SQL
> scripts' text-search admin steps must run on a local Db2 connection as the
> instance owner.

## Setup (one-time)

```bash
git clone <your-repo-url> db2-hybrid-search && cd db2-hybrid-search
```

Install the prerequisites — the full ordered guide is
**[install/README.md](install/README.md)** (prerequisites → OpenSearch → Db2 →
llama.cpp + models → Python → configure → verify). Each component also has an
automated installer under `install/` that installs, verifies, then leaves
the service stopped. In short (install OpenSearch before Db2 — Db2 registers it as
the Text Search backend):

```bash
./install/opensearch-install.sh                     # OpenSearch (Text Search backend)
sudo ./install/db2-install.sh /path/to/server_dec   # Db2 + instance + SAMPLE + Text Search
./install/llamacpp-install.sh                       # build llama.cpp + download bge-small
python3.12 -m venv .venv && source .venv/bin/activate && pip install -e .
```

Then configure the connection:

```bash
cp .env.example .env
$EDITOR .env          # Db2 connection + password (embeddings are local — no API keys)
```

`.env` is git-ignored — your real credentials are never committed.

## Usage — run the scripts in order

The filenames are numbered by execution order. After the one-time
[Setup](#setup-one-time), run them **0 → 2** as the Db2 instance owner from the
repo root — start the services, ingest your CSV corpus, then search — and
`3_stop-services.sh` when you're done. (Text Search is enabled once when you set
up Db2 — see [install/README.md](install/README.md).)

### 0. `0_start-services.sh` — start the services

The pipeline needs three services up — **Db2**, **OpenSearch**, and the **llama.cpp
embedding server** (Db2's `TO_EMBEDDING` calls it during ingest and search). After
the one-time [Setup](#setup-one-time), bring them all up:

```bash
./scripts/0_start-services.sh        # starts Db2, OpenSearch, and the embedding server
```

Idempotent (skips anything already up).

### 1. `1_ingest.sql` — CSV corpus → Db2

```bash
db2 -tvf scripts/1_ingest.sql
```

Drops any existing chunks table/index (so it's re-runnable), `IMPORT`s
`data/corpus.csv` into a fresh table, builds the Db2 Text Search index
(`SYSTS_CREATE`/`SYSTS_UPDATE`), registers the local embedding model
(`PROVIDER OPENAI` → llama.cpp), fills a `VECTOR` column via `TO_EMBEDDING`, and
builds the vector index.

The script reads a fixed filename, `data/corpus.csv` (the audiobook schema — one row
per book). Bring your own by matching that schema, or edit the `IMPORT FROM` line.

Before the first run: `db2set DB2_VECTOR_INDEXING=YES -immediate` (once), and make
sure the services from step 0 are up (`./scripts/0_start-services.sh`) so
`TO_EMBEDDING` can reach the embedding server. No secrets — it's local and keyless.
See [install/README.md](install/README.md).
**Leaves behind:** one table (default `myschema.chunks`) where every row has
`chunk_id`, `chunk_text`, a text-search index entry, and an `embedding` vector.

> Lexical-only: delete the model / embed / vector-index sections in
> `1_ingest.sql` (keep table + text index).

### 2. `2_search.sql` — hybrid retrieval

```bash
db2 -tvf scripts/2_search.sql
```

Runs all three legs for **one hardcoded query** and prints them: the **lexical**
leg (`CONTAINS` + BM25 `SCORE`), the **vector** leg (`VECTOR_DISTANCE` over the
query embedding), and the **hybrid** fusion — the gated, score-normalized weighted
sum, **all in one Db2 SQL query**. To search something else, edit the query text
in the three statements (the raw form for the vector leg and the `word OR word …`
form for the keyword leg). For dynamic ad-hoc queries, use the live demo UI, which
calls the same engine (`hybrid_search.core`).
**Leaves behind:** nothing — it's read-only.

**How the fusion works (and why not plain RRF).** Reciprocal Rank Fusion ranks
by position only, so a leg that is essentially guessing (vectors on an exact
error code, keywords on a pure paraphrase) injects its top guesses with the same
weight as the other leg's real hits — and they tie, so noise floats to the top.
Instead, the fusion (in [src/hybrid_search/core.py](src/hybrid_search/core.py)):
1. carries each leg's real score (BM25 `SCORE`, cosine similarity),
2. **gates** a leg out when its best score is below a threshold (a near-random
   leg contributes nothing — e.g. vectors whose top cosine similarity `< 0.30`),
3. **max-normalizes** the survivors to `(0,1]`, and
4. takes a **weighted sum**.
A document found by *both* legs is reinforced; a noisy leg is muted. The gates,
weights, and candidate-pool size are `.env`-tunable (`HYBRID_*`).

### 3. `3_stop-services.sh` — stop the services

```bash
./scripts/3_stop-services.sh          # stops the embedding server, OpenSearch, and Db2
```

### Measuring quality — `eval.py`

```bash
DB2_HOST=local PYTHONPATH=src python scripts/eval.py   # or: pip install -e . && DB2_HOST=local python scripts/eval.py
```

Scores a **golden eval set** (JSON of query → gold id(s), resolved from `$GOLDEN_SET`,
argv, or the newest `~/out/eval/golden_set.draft.v*.json`) against all three legs:
**known_item** queries → **MRR / Hits@1**; **topical** queries → **Recall@5 / nDCG@5**.
Results are reported for the **held-out** slice (never tuned on), TRAIN, and ALL, plus a
per-query-type diagnostic. Run it after any change to the corpus, embedding model, or
`HYBRID_*` knobs and judge by the numbers. Tune the knobs on TRAIN, confirm on HELDOUT.
See [docs/eval-results.md](docs/eval-results.md).

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

Written for the shipped audiobook corpus (`data/corpus.csv`) — adapt them to your own.
The principle is general: **exact terms favor keyword search, paraphrases favor
vectors, and a mix favors hybrid.** Try one in the demo UI, or put it into the query
text in `scripts/2_search.sql` (both the raw and `word OR word …` forms), then:

```bash
db2 -tvf scripts/2_search.sql
```

**Keyword search wins** — an exact name the embedding can't place:
- `teddy hamilton` → the narrator; keyword nails it while the vector leg wanders.
- `pragmatic programmer` → the exact title.

**Vector search wins** — plain-language descriptions using none of the book's own words:
- `why we so often misjudge people we've just met` → *Talking to Strangers*.
- `learning to say no so you focus on the vital few` → *Essentialism*.

**Hybrid wins** — an author or distinctive term *and* natural phrasing:
- `jason fung on reversing blood-sugar disease` → *The Diabetes Code*.
- `cal newport's book about accomplishing without burning out` → *Slow Productivity*.

## Configuration

Everything is configured via `.env`: Db2 connection, schema/table names, and
vector dimension. (Embeddings are local — no API keys; the embedding
model/endpoint is set in `1_ingest.sql`.) The fusion knobs
(`HYBRID_W_LEX`, `HYBRID_W_VEC`, `HYBRID_VEC_GATE`, `HYBRID_LEX_GATE`,
`HYBRID_POOL`) are optional — tune them against `eval.py`. See
[.env.example](.env.example).

## Repository layout

```
src/hybrid_search/   core.py (engine + fusion) · understanding.py (query cleaner) · rerank.py (cross-encoder stage)
install/   README.md (consolidated setup) + opensearch / db2 / llamacpp installers (install · verify · stop)
scripts/   services:             0_start-services.sh · 3_stop-services.sh
           pipeline:             1_ingest.sql · 2_search.sql
           eval:                 eval.py · smoke-test.sh
           query-understanding/  SQL gate + local generation server (optional; off by default)
           rerank/               cross-encoder reranker server + A/B harness (optional; off by default)
data/      corpus.csv — the audiobook corpus (bring your own, same schema)
tests/     test_demo_*.py · test_understanding.py · test_rerank.py
ui/        run.sh · build_fixtures.sh · api.py · demo_view.py · static/ (Search · Demo · Golden eval · Architecture)
docs/      eval-results.md
install/   README.md — one-time setup (Db2 · OpenSearch · llama.cpp · Python)
pyproject.toml · requirements.txt
```

## Docs

- [install/README.md](install/README.md) — **the** setup guide: prerequisites → components → configure → verify.
- [docs/eval-results.md](docs/eval-results.md) — search-quality evaluation results from `eval.py`.
- [ui/README.md](ui/README.md) — the demo UI: tabs, one-command run, design notes.
- [scripts/query-understanding/README.md](scripts/query-understanding/README.md) — the adaptive query-understanding gate (optional, off by default).
- [scripts/rerank/README.md](scripts/rerank/README.md) — the post-fusion cross-encoder reranker + A/B results (optional, off by default).

## License

[Apache-2.0](LICENSE).
