# Hybrid Search on IBM Db2 12.1.5

Keyword search **and** semantic (vector) search over the same data, fused into one
ranking — built entirely inside **IBM Db2 12.1.5**, with a small local embedding
server. No external vector database, no separate search service to keep in sync.
One Db2 table is the source of truth.

This README takes you from **a bare Red Hat machine to a running app**, step by
step. No prior Db2, OpenSearch, or embeddings experience assumed.

---

## Contents

- [What it does & why](#what-it-does--why)
- [Architecture](#architecture-one-row-two-representations)
- [See it in 30 seconds (no install)](#see-it-in-30-seconds-no-install)
- [Full setup on a fresh RHEL box](#full-setup-on-a-fresh-rhel-box) ← the main guide
- [Run the pipeline](#run-the-pipeline-ingest--search)
- [Run the app](#run-the-app)
- [Try it: example queries](#try-it-example-queries)
- [Measure search quality](#measure-search-quality)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Repository layout](#repository-layout)

---

## What it does & why

Most "AI search" demos do only half the job. Real retrieval works best when you
combine **two** ways of finding text, because each has a blind spot:

- **Lexical** (keyword / BM25) — great at exact terms: names, titles, error codes,
  identifiers. Blind to paraphrases.
- **Semantic** (vector embeddings) — great at meaning: synonyms and descriptions.
  Blind to exact tokens it can't place (a bare narrator name embeds to noise).

This project stores each row of a CSV corpus in Db2 with **both** representations,
searches with both, and **fuses** the two rankings so each leg covers the other's
blind spot. It uses Db2 12.1.5 features end to end:

- **Db2 Text Search** (OpenSearch-backed) for the lexical/BM25 index, and
- **native `VECTOR` columns + in-database `TO_EMBEDDING`** (via a registered
  OpenAI-compatible model — a local llama.cpp `bge-small-en-v1.5` server) for the
  semantic index.

The shipped corpus is a personal audiobook library (92 books; `chunk_text` =
title + authors + narrators + full description). Both retrieval legs index this
text — BM25 over all of it, the vector over the first ~1500 chars (the embedding
model's 512-token limit). Bring your own by matching that schema.

## Architecture: one row, two representations

```
CSV corpus (chunk_id, chunk_text)
        │  1_ingest.sql
        ▼
Db2 table  (chunk_id, chunk_text, embedding)
       ├── chunk_text → Db2 Text Search index (OpenSearch)      → BM25 / CONTAINS · SCORE
       └── embedding  → native VECTOR column (local bge-small)  → cosine · VECTOR_DISTANCE
                            │
                            ▼
       fuse both legs (gated, score-normalized weighted sum) — all in one Db2 SQL query
```

The fusion is **not** plain Reciprocal Rank Fusion — see
[How the fusion works](#how-the-fusion-works-and-why-not-rrf).

---

## See it in 30 seconds (no install)

Before installing anything, you can run the **offline demo**. It serves a frozen
snapshot of real search results — no Db2, no Python packages, no models. You only
need `git` and Python 3.

```bash
git clone <your-repo-url> db2-hybrid-search && cd db2-hybrid-search
./ui/run.sh                     # serves the static demo
```

Open **http://127.0.0.1:8000**. You'll land on a **Start here** page, then a
**Demo** tab that shows — for real queries — where each single retriever fails and
hybrid succeeds. Stop with `Ctrl-C`.

This is the whole point of the project, visible before you commit to the full
install. When you're ready for live search over your own data, continue below.

---

## Full setup on a fresh RHEL box

**What you're building:** OpenSearch (the keyword-index backend) → Db2 (the
database + vector engine) → a local embedding server → the Python project → your
data ingested → the app.

**Time & footprint:** ~30–45 min, mostly downloads. CPU-only is fine (no GPU).
Budget ~2 GB RAM for OpenSearch and a few GB for Db2. Developed on **RHEL 10**.

**You will need:** root/sudo (for installs), the **Db2 12.1.5 server install
media**, and internet access. Everything is scriptable except obtaining the Db2
media, which requires an IBM entitlement.

> **Run the project steps as the Db2 instance owner** (e.g. `db2inst1`). Db2's
> text-search admin steps and the fast local connection require it.

Each component below has an **automated installer** in [`install/`](install/) that
installs, verifies, and leaves the service stopped. The commands here are the happy
path; [install/README.md](install/README.md) is the detailed reference (manual
steps, every option, and a Gotchas table) — read it if a step fails or you already
have Db2 installed.

### Step 0 — System packages

```bash
sudo dnf install -y git cmake gcc-c++ python3.12 \
                    libaio libstdc++ ksh pam numactl-libs libnsl libxcrypt-compat
```
`git`/`cmake`/`gcc-c++` build the embedding server; `python3.12` is the project
runtime (already present on RHEL 10.2); the rest are **Db2 prerequisites**.
`libxcrypt-compat` (provides the legacy `libcrypt.so.1`) is required on RHEL 10 —
without it `db2prereqcheck` fails with `DBT3507E`.

> Db2's own `db2prereqcheck` lists every missing package for your exact version —
> run it from the install media, install whatever it names, and re-run until clean.

### Step 1 — Get the code

```bash
git clone <your-repo-url> db2-hybrid-search && cd db2-hybrid-search
```

### Step 2 — OpenSearch (install **before** Db2)

Db2 Text Search registers OpenSearch as its backend, so OpenSearch must exist first.

```bash
./install/opensearch-install.sh
```
**Does:** raises the OS `vm.max_map_count`, downloads OpenSearch 3.7.0 into
`/opt/opensearch`, configures a single-node cluster (security disabled — local use
only), verifies it starts, then stops it.
**You should see:** a success line; `curl http://localhost:9200` returns cluster
JSON while it's running.

### Step 3 — Db2 12.1.5 + instance + Text Search

```bash
sudo ./install/db2-install.sh /path/to/server_dec
```
`/path/to/server_dec` is the extracted Db2 install media directory.
**Does (as root, then as the new `db2inst1`):** installs Db2, creates the
`db2inst1` instance, builds the `SAMPLE` database, enables Db2 Text Search and
registers OpenSearch as the backend, sets `DB2_VECTOR_INDEXING=YES`, then leaves
Db2 stopped. It prompts you to set the `db2inst1` password.
**You should see:** `OK — Db2 installed, instance 'db2inst1' created, SAMPLE built,
Text Search enabled…`.

> Already have Db2 installed? Skip the installer and follow
> [install/README.md §2](install/README.md#2-db2-1215--instance--text-search) to
> enable Text Search and register OpenSearch by hand.

### Step 4 — Local embedding server (llama.cpp + model)

```bash
./install/llamacpp-install.sh
```
**Does:** builds `llama-server` from source, downloads the `bge-small-en-v1.5`
embedding model (~37 MB), and verifies it returns **384-dimensional** vectors.
**You should see:** `dim 384`. (The optional reranker and generation models are
off by default — see [install/README.md §3](install/README.md#3-llamacpp--models-local-keyless).)

### Step 5 — Python project

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```
**Does:** creates a virtualenv and installs the engine (`ibm_db`, FastAPI, uvicorn)
and makes `hybrid_search` importable. For the test suite, add:
`pip install -e ".[test]"` (see [tests/README.md](tests/README.md)).

### Step 6 — Configure `.env`

```bash
cp .env.example .env
$EDITOR .env
```
The pipeline and app connect **locally as the instance owner** (fast, no password),
so most defaults are fine out of the box. Set `DB2_PASSWORD` (and `DB2_PORT`, if
you'll ever connect over TCP — find it with the snippet in
[install/README.md §2](install/README.md#2-db2-1215--instance--text-search)).
`.env` is git-ignored; real credentials are never committed.

### Step 7 — Start services

```bash
./scripts/0_start-services.sh      # starts Db2, OpenSearch, embedding server (idempotent)
```
**You should see:** each service reported as `running`/`starting`. OpenSearch takes
~1 min to accept connections the first time. (The full `smoke-test.sh` runs *after*
ingest, below — it does an end-to-end search, so it needs the corpus loaded first.)

That's the one-time setup. **Everything below is the day-to-day workflow.**

---

## Run the pipeline (ingest → search)

Ingest your corpus into Db2, then search it. Run these as the instance owner, from
the repo root, with the services up (Step 7).

```bash
./scripts/preflight.sh && db2 -tvf scripts/1_ingest.sql
```
**Always run `preflight.sh` first.** It waits for OpenSearch and the embedding
server and fails with a clear message if either is down. Skipping it is the single
most confusing way to break setup — a stopped OpenSearch makes ingest reject *every
row as a duplicate key*, which looks like a data problem but is really a stopped
service.

`1_ingest.sql` drops any existing table/index (so it's re-runnable), imports
`data/corpus.csv`, builds the Db2 Text Search index, registers the local embedding
model, fills a `VECTOR` column via `TO_EMBEDDING`, and builds the vector index.
**You should see:** `92 rows … successfully inserted`, then several
`DB20000I … completed successfully`.
**Leaves behind:** one table (`myschema.chunks`) where every row has `chunk_id`,
`chunk_text`, a text-search index entry, and an `embedding` vector.

Now verify the whole engine end-to-end — services **and** a real search:

```bash
./scripts/smoke-test.sh
```
**You should see:** `SMOKE TEST: PASS`. (Run this only *after* ingest — it searches
the corpus, so it fails with `MYSCHEMA.CHUNKS_EMBED is an undefined name` if
`1_ingest.sql` hasn't run yet.)

Then run the reference search — all three legs for one query, in one Db2 statement:

```bash
db2 -tvf scripts/2_search.sql
```
It prints the **lexical**, **vector**, and **hybrid** rankings side by side. To
search something else, either edit the query text in that file, or use the app
(next), which takes typed queries.

When you're done for the day: `./scripts/3_stop-services.sh`.

> Using your own data? Match the CSV schema in `data/corpus.csv` (the `IMPORT` in
> `1_ingest.sql` is positional), or edit the `IMPORT FROM` line. For lexical-only,
> delete the model/embed/vector sections of `1_ingest.sql`.

---

## Run the app

A web demo that shows each retriever's blind spot and how hybrid covers it.

```bash
./ui/run.sh                 # OFFLINE: static page + frozen results, no Db2 needed → http://127.0.0.1:8000
./ui/run.sh --live          # LIVE: type any query, answered by the real engine; API docs at /docs
```
- **Offline** is the conference/demo path — it serves committed fixtures, so it
  runs anywhere with just Python 3.
- **Live** answers ad-hoc queries against Db2 (needs Step 7's services up).

See [ui/README.md](ui/README.md) for the tabs and design notes.

---

## Try it: example queries

For the shipped corpus. The principle is general: **exact terms favor keyword
search, paraphrases favor vectors, a mix favors hybrid.** Type one in the app's
Search tab, or use the Demo tab which runs curated cases automatically.

**Keyword wins** — an exact token the embedding can't place:
- `walter dixon` — the narrator's name; keyword nails it, the vector leg wanders off.
- `pragmatic programmer` — the exact title.

**Vector wins** — a description using none of the book's own words:
- `why we so often misjudge people we've just met` → *Talking to Strangers*.
- `coping with stress` → *How to Stop Worrying and Start Living* (keyword finds nothing).

**Hybrid wins** — an author/topic mix where both legs contribute:
- `jason fung reversing type 2 diabetes` → *The Diabetes Code*.
- `cal newport focus without burnout` → *Slow Productivity*.

The **Demo** tab has a sharper case — *"getting past procrastination and just
starting"*, where neither leg ranks *Eat That Frog* in its own top results but
fusion lifts it into view. That's hybrid doing what neither leg can alone.

## How the fusion works (and why not RRF)

Reciprocal Rank Fusion ranks by *position only*, so a leg that is essentially
guessing (vectors on an exact code, keywords on a pure paraphrase) injects its top
guesses with the same weight as the other leg's real hits — and they tie, so noise
floats up. Instead, the fusion (in [src/hybrid_search/core.py](src/hybrid_search/core.py)):

1. carries each leg's real score (BM25 `SCORE`, cosine similarity),
2. **gates** a leg out when its best score is below a threshold (off by default),
3. **max-normalizes** the survivors to `(0,1]`, and
4. takes a **weighted sum** (default `0.3·lexical + 0.7·vector`).

A document found by *both* legs is reinforced; a noisy leg is muted. Weights,
gates, and pool size are `.env`-tunable (`HYBRID_*`) — and **corpus-specific**;
re-tune with `eval.py` on your data.

## Measure search quality

```bash
DB2_HOST=local PYTHONPATH=src python scripts/eval.py
```
Scores the shipped **golden eval set** ([data/eval/golden_set.json](data/eval/golden_set.json))
against all three legs — MRR/Hits@1 for known-item queries, Recall@5/nDCG@5 for
topical — reported on a held-out slice (never tuned on), TRAIN, and ALL, with a
per-query-type diagnostic. Run it after any change to the corpus, embedding model,
or `HYBRID_*` knobs. Results and method: [docs/eval-results.md](docs/eval-results.md).

## Configuration

Everything is in [`.env`](.env.example): the Db2 connection and the optional
`HYBRID_*` fusion knobs (weights, gates, candidate-pool size). Embeddings are local
— no API keys. The schema/table names are fixed by the SQL scripts (see the note in
`.env.example`). The `QU_*` (query understanding) and `RERANK_*` (cross-encoder)
features ship **off**.

## Troubleshooting

The most common failure is running the pipeline with a service down. `preflight.sh`
and `smoke-test.sh` catch that. The full symptom→cause→fix table is in
[install/README.md § Gotchas](install/README.md#gotchas) — including the
duplicate-key ingest failure (a stopped OpenSearch) and the "find your Db2 port"
snippet.

## Repository layout

```
src/hybrid_search/   core.py (engine + fusion) · evalset.py (golden-set resolver)
                     understanding.py · rerank.py (optional stages, off by default)
install/   README.md (setup guide) + opensearch / db2 / llamacpp installers
scripts/   services: 0_start-services.sh · 3_stop-services.sh
           pipeline: preflight.sh · 1_ingest.sql · 2_search.sql
           quality:  eval.py · smoke-test.sh
           query-understanding/ · rerank/   (optional; off by default)
data/      corpus.csv (the audiobook corpus) · eval/golden_set.json (eval queries)
ui/        run.sh · build_*.sh · api.py · static/ (Start · Search · Demo · Eval · Architecture)
tests/     README.md + test_*.py  (skip cleanly without Db2 / browser)
docs/      eval-results.md
```

## Docs

- **[install/README.md](install/README.md)** — the detailed setup reference + Gotchas.
- [tests/README.md](tests/README.md) — how to run the six test suites.
- [docs/eval-results.md](docs/eval-results.md) — search-quality evaluation.
- [ui/README.md](ui/README.md) — the demo UI internals.
- [scripts/query-understanding/README.md](scripts/query-understanding/README.md) · [scripts/rerank/README.md](scripts/rerank/README.md) — optional stages (off by default).

## License

[Apache-2.0](LICENSE).
