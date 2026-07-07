# Demo UI — Hybrid Search on Db2 12.1.5

A minimalist demo that shows, in a few clicks, that **each single retriever has a
blind spot and hybrid search covers both**. Built for a mixed room (executives,
customers, developers) on a projector.

## Run it (one command, offline)

```bash
./ui/run.sh                 # http://127.0.0.1:8000  — static page + frozen fixtures
```

The talk path needs **no Db2, no embedding server, no pip** — just Python's stdlib server
reading `static/fixtures.json`. Robust on a conference laptop.

### Refreshing the data

Fixtures are frozen results of every demo query through all three strategies.
Regenerate them whenever the corpus, embedding model, or fusion knobs change:

```bash
./ui/build_fixtures.sh      # runs the real search (as db2inst1, local) -> static/fixtures.json
```

### Live mode (ad-hoc queries, for Q&A)

```bash
./ui/run.sh --live          # FastAPI backend hits the real engine; Swagger at /docs
```

## What you see

- **Left rail** — the curated deck: each query tagged Keyword / Semantic / Mixed
  with its gold chunk ID. Click to load it.
- **Center** — search box + a single-select strategy control (Lexical · Vector ·
  Hybrid). Selecting **Hybrid** shows that it subsumes the other two and opens the
  three-column comparison.
- **Hero badge** — where the gold chunk ranked (`#1…#5` or *not in top 5*).
- **Comparison** — Lexical | Vector | Hybrid side by side, each with its own gold
  badge; only the Hybrid column tags each result with `found_by` (BM25 / Vector).
- **Toggles** (off by default) — *Show scores* (raw BM25/cosine + normalized
  fusion contribution) and the cross-set *hit-rate* strip.

## Acceptance walk-through (`42615`)

1. Click **42615** in the left rail.
2. **Vector** → hero badge: *gold not in top 5* (vectors can't embed a bare code).
3. **Lexical** → gold at **#1**.
4. **Hybrid** → three columns; gold sits at **#1** in the Hybrid column, tagged
   **BM25** — rescued by the retriever that caught it.

## Color = strategy (always with a text label)

Lexical/BM25 = coral · Vector = teal · Hybrid/both = purple · gold found = green ·
gold missed = muted amber. Monospace for chunk IDs and scores.

## Files

```
queries.json        curated deck + gold IDs (single source; scripts/eval.py reads it too)
build_fixtures.py   freeze every query x 3 strategies -> fixtures.json
build_fixtures.sh   wrapper (runs as db2inst1, local connection)
api.py              live backend (--live only); same JSON shape as fixtures
run.sh              one-command launcher (offline default | --live)
static/             index.html · styles.css · app.js · fixtures.json · queries.json
```

The search engine and the gated, score-normalized fusion live in
`../scripts/hybrid_core.py`. The fusion is **not** RRF — each leg's score is
normalized and low-confidence legs are gated out before a weighted sum.

## Honesty

No weights, gates, chunk text, or results were tuned to make hybrid win. Ranks
are whatever the engine returns; the curated set spans the failure modes
(exact-code, paraphrase, and agree cases).

## Not in v1 (future)

- Fusion animation / transitions beyond simple ones.
- Free-text ad-hoc queries in **offline** mode (use `--live`).
- Editable weights/gates from the UI.
