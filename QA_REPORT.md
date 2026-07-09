# Release Audit — QA Report

**Repo:** hybrid-search · **Branch:** `phase-2` · **Scope:** functional QA, docs
consolidation, replication cleanup. **Ground rule honored:** nothing hard-deleted —
every removal is a reversible `git mv` into `backup/`.

---

## Phase 0 — Inventory (no changes)

- **Git:** it *is* a git repo; working tree was clean/pushed before the audit.
  `.env` is untracked (secrets safe), `.env.example` tracked, `src/hybrid_search.egg-info/`
  untracked (build artifact).
- **Artifact map (core):** `core.py` is the hub (imported by `understanding.py`,
  `rerank.py`, `eval.py`, `ui/build_fixtures.py`, `ui/api.py`, tests). `responses_for`
  (build_fixtures) feeds `/api/search`, `/api/demo`, `build_demo`. The golden set
  (`~/out/eval/golden_set.draft.v*.json`) feeds `eval.py`, `qu_eval.py`, `rerank_eval.py`,
  `build_demo.py`.

---

## Phase 1 — Functional QA

| Check | Result |
|---|---|
| Test suite (5 suites) | **435 passed / 0 failed** — rerank 20 · understanding 14 · demo_view 336 · demo_ui 37 · demo_e2e 28 |
| `test_backend.py` | **FAIL → archived** — hardcoded old-corpus query returns 0 lexical hits → `IndexError`; superseded by `test_demo_ui` TestClient smoke |
| Entry: `0_start-services` | Db2 / OpenSearch(:9200) / embedding(:8085) all up |
| Entry: `1_ingest.sql` | corpus ingested (engine + tests depend on it) ✓ |
| Entry: `2_search.sql` | runs; all three legs return #61 *The Diabetes Code* ✓ (was stale — fixed) |
| Entry: `eval.py` | resolves golden set from `$GOLDEN_SET`/argv/newest draft ✓ |
| Entry: `smoke-test.sh` | **PASS** (services + real hybrid search) |
| Install scripts | `bash -n` clean on all 11 shell scripts |
| Secrets / personal paths | **none in tracked code/scripts**; only a placeholder `api-keyxxxxx` inside the now-archived `sample_chunks.csv` |
| Versions | pyproject `>=3.12`; `ibm_db 3.2.9 · fastapi 0.115.6 · uvicorn 0.34.0` — consistent with README. Gap: `playwright` (e2e dep) undeclared → documented in `install/README` |

---

## Phase 2 — Content findings & actions

| # | Location | Finding | Action |
|---|---|---|---|
| 1 | `README.md:41` | Diagram called fusion **RRF** — contradicts its own §2 ("why not RRF") | **update** → "gated, score-normalized weighted sum (not RRF)" |
| 2 | `README.md` | Described the **old** corpus (`sample_chunks.csv`, SQLSTATE `42615` examples) | **update** → audiobook `corpus.csv` + audiobook example queries |
| 3 | `README.md` | Repo-layout + Docs sections stale (no `understanding.py`/`rerank.py`/`arch.js`/new tests; dead-ish doc links) | **update** → current layout + `install/README` + QU/rerank READMEs |
| 4 | `scripts/2_search.sql` | Stale hardcoded query **and** stale knobs (POOL 50, .5/.5, gate .30) | **update** → audiobook query + tuned knobs (POOL 97, .1/.9, gates 0); verified |
| 5 | `ui/README.md` | Stale: single-select "Vector" UI, `42615` walk-through, wrong "eval.py reads queries.json", missing tabs/files | **update** → rewritten for the 4-tab UI |
| 6 | `ui/DEMO_QA_REPORT.md` | 0 references; stale (129 tests vs 435; old Search tab; `?v=3`) | **archive** → `backup/ui/` |
| 7 | `data/sample_chunks.csv` | Not used by code (ingest uses `corpus.csv`); incompatible schema; placeholder key | **archive** → `backup/data/` |
| 8 | `tests/test_backend.py` + `ui/test_backend.sh` | Broken (old-corpus query) + superseded | **archive** → `backup/` |
| 9 | `docs/{db2,opensearch,llamacpp,local-embeddings}-setup.md`, `docs/setup-and-run.md` | Install content, duplicated + some corpus staleness | **merge → archive** (into `install/README`, originals in `backup/docs/`); inbound links repointed to `install/README`, so `docs/` now holds only `eval-results.md` |
| 10 | install docs | **No coverage** of the reranker (:8087) or generation (:8086) servers | **update** → added to `install/README` with the two-process note |
| 11 | `docs/eval-results.md` | Current (audiobook corpus) | **keep** |

---

## Phase 3 — Consolidation summary

- **`install/` is now the single home for setup** — the three installers
  (`opensearch-install.sh`, `db2-install.sh`, `llamacpp-install.sh`) moved from
  `scripts/install/` into `install/` alongside the guide; all references updated
  (they have no self-relative path logic, so the move is safe).
- **Created `install/README.md`** — one ordered guide: prerequisites (OS, versions,
  CPU, **ports table**) → OpenSearch → Db2 → llama.cpp + models → Python → configure →
  start → verify. Install instructions preserved **verbatim** from the source docs;
  added the reranker + generation servers and the note that **`--embedding` and
  `--reranking` are mutually exclusive, so llama.cpp runs as separate processes on
  separate ports** (8085 / 8086 / 8087).
- **Moved to `backup/` (reversible `git mv`):** 5 setup docs, `sample_chunks.csv`,
  `DEMO_QA_REPORT.md`, `test_backend.py`, `test_backend.sh`.
- **`docs/` cleaned** — all inbound links (README, `eval-results.md`, install-script
  comments) repointed to `install/README.md`, so `docs/` now holds only `eval-results.md`.
  **All internal markdown links resolve** (checked).

---

## Phase 4 — Replication checklist

| Item | Status |
|---|---|
| One path: clone → prereqs → install → configure → verify | ✅ README quickstart points at `install/README.md` |
| Single externalized config | ✅ `.env.example` (Db2 · HYBRID · QU · RERANK · serving paths/ports) |
| Secrets stripped from scripts/docs | ✅ none in tracked files (placeholder key archived with `sample_chunks.csv`) |
| Setup smoke test | ✅ `scripts/smoke-test.sh` → **PASS** (services + end-to-end search) |
| Idempotent / re-runnable installs | ✅ `0_start-services.sh` idempotent; `1_ingest.sql` re-runnable (drops+rebuilds); installers self-skip |
| README orients a newcomer | ✅ what it is · architecture-at-a-glance · quickstart → `install/README` |

---

## Open items (non-blocking, flagged not fixed)

- **`data/corpus.csv` is the maintainer's personal audiobook library**, committed as the
  demo corpus. Kept (the engine + eval depend on it); a cloner brings their own matching
  the schema, or edits `1_ingest.sql`. Swap it out if you'd rather ship a neutral sample.
- **`.env.example` kept at repo root**, not a new `config/` subdir — moving it would break
  `core.py`'s `.env` load path and every doc reference for no functional gain; the goal
  (one externalized, secret-free config file) is met. Say the word to introduce `config/`.
- **`playwright` not in `requirements.txt`** (test-only, heavy) — documented as a test dep
  in `install/README` instead of forced on every install.
- **`src/hybrid_search.egg-info/`** is an untracked build artifact — confirm `.gitignore`
  covers `*.egg-info/`.

## Definition of done — **GREEN**

Functional suite green (435/0), entry points execute, smoke test passes, no secrets or
dead links, install consolidated with verbatim content preserved and every move reversible
in `backup/`. Open items above are choices for the maintainer, not defects.
