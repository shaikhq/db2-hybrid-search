# Plan: "Label" tab — pooled relevance-labeling interface

**Status:** approved, not yet implemented.
**Goal:** build a better eval set by labeling *pooled* retrieval results (TREC-style) directly inside the demo app.

## Why

The golden set is small and hand-picked. To grow it with defensible judgments, use
**pooling**: for a query, take the top-10 from *each* retriever (lexical + dense vector),
union them, discard rank, and label each unique document Relevant / Irrelevant. The
relevant set for a query becomes its `gold_ids`.

Manual workflow this automates:
1. Write ~20 queries by hand.
2. Take the top 10 results from each index for every query.
3. Discard rank order; combine into one unranked list (dedup).
4. Label each result document relevant / irrelevant against the query.

## Design decisions (approved)

- **Integrated Label tab** in the existing app (not a separate tool).
- **Separate store** `data/eval/judgments.json` + an exporter that emits `gold_ids`
  (do not hand-edit `golden_set.json`).
- **Queries are typed in the interface** (no preloaded query list required).
- Standardize on **`gold_ids`** end-to-end; leave the demo decks' `gold_chunk_ids` untouched.
- Labels: **Relevant / Irrelevant / Skip**. Auto-save on each click. Rank and which
  leg surfaced a doc are **hidden** during judging (avoid anchoring bias).

## Interaction contract (approved)

The labeling loop is ~20 queries × ~15 pooled docs ≈ 300 judgments, and the assessor
calibrates what "relevant" means *while* working a query. Both facts drive the decisions
below. Guiding principles, inherited from the design decisions above: **don't bias the
assessor**, and **never lose a judgment**.

1. **Labeling a card collapses it in place — it is not removed.** The card shrinks to
   title + a colored label chip, keeps its position in the list, and the list scrolls so
   the next *unlabeled* card is at the top. Rationale: relevance for a query is calibrated
   across its pool (the 12th doc often reveals the 3rd was borderline). A card that
   vanishes on click makes recalibration impossible and bakes assessor inconsistency into
   `gold_ids`.
   - **Keyboard:** `1` = relevant, `2` = irrelevant, `3` = skip, `u` / `Backspace` = undo
     last. Keyboard-first is required at this volume, not a nicety.

2. **Labels are freely changeable.** Click (or key) a different label on a collapsed card
   to overwrite it. No confirmation dialog, no separate edit mode. The backend is already
   idempotent per `(query, cid)`, so this costs nothing; assessors demonstrably contradict
   themselves, and a tool that makes correction hard hides inconsistency rather than
   preventing it.

3. **Pools always rehydrate.** "Build pool" fetches `GET /api/pool?q=` **and**
   `GET /api/judgments` and renders the pool with existing labels already applied. The
   `md5(q)` shuffle seed exists precisely so a resumed query has a stable order. Progress
   counts and "next unlabeled card" must both compute from the **merged** state, never
   from clicks made in the current session.

4. **Progress is two numbers, not one:** `n decided / m in pool` where
   `decided = relevant + irrelevant + skip`, plus a separate `k skipped` (skips are the
   revisit queue). A query is **complete** when `decided == m`; completeness has an
   explicit visual state, because the exporter's `query_class` rule is only correct over a
   complete relevant set (see Exporter).

5. **Empty / partial pools are distinct, visible states — never a silently blank list.**
   - Both legs empty → "No results for this query — nothing to label."
     **Write no judgments entry for the query.**
   - One leg empty → render normally, but note it (e.g. "pool built from 1 of 2
     retrievers"). A query where lexical returns nothing and vector returns ten is a real
     signal about the system, not an error.
   - Heavy leg overlap → just report the true post-dedup `m`.

## Frontend

- `ui/static/index.html`
  - New nav button: `<button class="tab" data-page="label" …>Label</button>`.
  - New `<section class="labelpage" id="page-label" hidden>` with a query box, a
    "Build pool" action, a progress line (`n labeled / m in pool`), and a card list.
  - Bump cache-bust to `?v=57` on all static asset links; add `label.js?v=57`.
- `ui/static/label.js` — new global-scope module `labelBoot()`, mirroring the existing
  plain-script pattern. Reuses `resultCard` / `coverImg` / `highlight` / `setPage` / `LIVE`
  from `app.js`. Per card: Relevant / Irrelevant / Skip buttons; clicking POSTs the
  judgment and advances. No rank or leg badge shown.
- `ui/static/styles.css` — `.labelpage` styles (reuse existing card styles).

## Backend (`ui/api.py`, all GET/POST loopback)

- `GET /api/pool?q=` — union `core.lexical(conn, q, 10)` + `core.vector(conn, q, 10)`,
  dedup by chunk id, **discard rank**, deterministic shuffle (seed = `md5(q)`), attach
  `book_meta` per cid. Returns the unranked pool for labeling.
- `GET /api/judgments` — return the current judgments store.
- `POST /api/judgments` — read-merge-write a single `{query, cid, label}` judgment with an
  **atomic rename** (write temp, `os.replace`). Idempotent per (query, cid).

## Persistence

- Store path via env `JUDGMENTS_PATH`, defaulting to `$REPO/data/eval/judgments.json`.
- **Critical:** the `--live` server runs from an ephemeral, per-launch-wiped stage
  (`/tmp/hybrid-ui-$PORT`). So `ui/run.sh`'s `--live` branch must `export
  JUDGMENTS_PATH="$REPO/data/eval/judgments.json"` (a path under the real repo, not the
  stage) before launching uvicorn — otherwise labels are lost on the next launch.

## Exporter

- `scripts/export_judgments.py` — read `judgments.json`; per query, `relevant` cids →
  `gold_ids`; set `query_class = known_item` if exactly 1 relevant else `topical`;
  `review_status = "verified"`, `source = "labeled"`, `split = "train"`. Reuse the id/
  numbering + corpus-map patterns from `scripts/filter_eval_candidates.py`. Emits entries
  in `golden_set.json` shape (append / merge, don't clobber existing).

**Two guards (added with the interaction contract — both prevent silent bad eval data):**

- **Skip incomplete queries by default.** The `known_item` vs `topical` rule reads the
  *complete* relevant set. A query abandoned after 4 of 15 docs with 1 relevant so far
  exports as `known_item` when it is actually `topical` — wrong, with no error raised.
  Export only queries where every pooled doc has a decision; `--include-partial` overrides.
  (This requires the exporter to know the pool size per query — persist `pool_size`
  alongside `labels` in `judgments.json`, since the pool is otherwise only reconstructible
  by re-running retrieval.)
- **Skip queries with zero relevant judgments**, and log every skip. Emitting
  `gold_ids: []` creates an eval entry no retriever can satisfy, silently depressing
  recall for reasons that are hard to trace back.

## Tests

- Extend `tests/test_demo_ui.py`: Label tab renders, pool endpoint shape, POST persists,
  atomic write, re-POST of the same `(query, cid)` overwrites rather than duplicates,
  empty-pool query writes no entry.
- New `tests/test_export_judgments.py`: relevant→`gold_ids`, known_item vs topical class,
  merge without clobber, incomplete query skipped (and included under `--include-partial`),
  zero-relevant query skipped.

## judgments.json shape (draft)

```json
{
  "queries": {
    "how to build better habits": {
      "pool_size": 15,
      "labels": { "66": "relevant", "39": "irrelevant", "63": "skip" }
    }
  }
}
```

## Out of scope (for the first pass)

- No auth (loopback only, same as the rest of the live app).
- No multi-annotator agreement / adjudication.
- No editing of `gold_chunk_ids` demo decks.

## Starting point for a fresh session

**No code has been written yet** — this is a self-contained spec. Implement in this order:

1. **Backend** — add the three routes to `ui/api.py` (`GET /api/pool`, `GET /api/judgments`,
   `POST /api/judgments`). Reuse `core.lexical`, `core.vector`, `core.book_meta`. Atomic
   write via temp-file + `os.replace`. `POST` records `pool_size` for the query (needed by
   the exporter's completeness guard) and writes nothing for an empty pool.
2. **Persistence** — in `ui/run.sh`'s `--live` branch, `export
   JUDGMENTS_PATH="$REPO/data/eval/judgments.json"` before launching uvicorn (the stage in
   `/tmp/hybrid-ui-$PORT` is wiped every launch, so the store must point at the real repo).
3. **Frontend** — add the `Label` tab button + `#page-label` section in
   `ui/static/index.html`; new `ui/static/label.js` (`labelBoot()`), reusing
   `resultCard` / `coverImg` / `highlight` / `setPage` / `LIVE` from `app.js`; `.labelpage`
   styles in `styles.css`; bump every static asset cache-bust `?v=56` → `?v=57` and add
   `label.js?v=57`. Implements the **Interaction contract** section above in full
   (collapse-in-place, keyboard, relabel, rehydrate, two-number progress, empty states).
4. **Exporter** — `scripts/export_judgments.py` (patterns from
   `scripts/filter_eval_candidates.py`).
5. **Tests** — extend `tests/test_demo_ui.py`; add `tests/test_export_judgments.py`.

**Verify live:** `./ui/run.sh --live`, open the Label tab, type a query, build the pool,
label a few, confirm they land in `data/eval/judgments.json`, run the exporter.

**Standing constraints:** write "Db2" casing in any prose/UI; do NOT commit unless the user
asks; never add a Claude co-author trailer.
