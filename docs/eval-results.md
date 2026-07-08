# Evaluation Results — Hybrid Search (audiobook corpus)

Search-quality results from `scripts/eval.py` against the personal audiobook
corpus (one row per book; `chunk_text` = title + authors + narrators + description).

- **Reproduce:** `DB2_HOST=local PYTHONPATH=src python scripts/eval.py` (or `pip install -e .` then drop `PYTHONPATH`)
- **Golden eval set:** `~/out/eval/golden_set.draft.v*.json` — **112 silver queries** (`needs_review`), 96/96 book coverage, stratified into TRAIN (90) / **HELDOUT (22, ~20%)**. known_item queries have one gold book; topical queries list all qualifying books.
- **Corpus:** 97 audiobooks in Db2 `MYSCHEMA.CHUNKS` (book [45] "Your First Listen" excluded — placeholder).
- **Embeddings:** local **bge-small-en-v1.5** (384-dim) via llama.cpp / Db2 `PROVIDER OPENAI` — see [local-embeddings.md](local-embeddings.md). Queries carry bge's retrieval instruction; passages embedded raw.
- **Fusion knobs:** tuned on TRAIN (`HYBRID_W_LEX=0.1 W_VEC=0.9 VEC_GATE=0.0 LEX_GATE=0.0 POOL=97`).
- **Date:** 2026-07-08

Metrics: **known_item →** MRR, Hits@1. **topical →** Recall@5, nDCG@5.

## HELDOUT — the honest number (never tuned on)

| leg | MRR | Hits@1 | Recall@5 | nDCG@5 |
|---|---|---|---|---|
| lexical | 0.816 | 0.789 | 0.556 | 0.588 |
| **vector** | **0.947** | **0.947** | **0.917** | **0.944** |
| hybrid (tuned) | 0.921 | 0.895 | 0.806 | 0.866 |

## ALL 112 queries

| leg | MRR | Hits@1 | Recall@5 | nDCG@5 |
|---|---|---|---|---|
| lexical | 0.786 | 0.729 | 0.467 | 0.527 |
| vector | 0.889 | 0.823 | 0.627 | 0.692 |
| hybrid (tuned) | 0.880 | 0.823 | 0.571 | 0.653 |

## Diagnostic — known_item MRR by query type (leg-level, knob-independent)

| query_type | lexical | vector |
|---|---|---|
| keyword | 0.975 | 0.975 |
| semantic | 0.185 | 0.635 |
| mixed | 0.855 | 0.911 |

This is the eval set validating itself: **semantic** queries score **0.185** on the
lexical leg (they defeat keyword matching — the vocabulary rule held), while
**keyword** queries ace it. Note the vector leg *also* aces keyword queries (0.975):
because `chunk_text` embeds the title/author/narrator, the dense leg already carries
the lexical signal.

## Tuning: baseline → tuned (HELDOUT)

| | baseline (.5/.5, gate .3, pool 50) | tuned (.1/.9, gates 0, pool 97) |
|---|---|---|
| hybrid MRR | 0.868 | **0.921** |
| hybrid Hits@1 | 0.842 | **0.895** |
| hybrid Recall@5 | 0.778 | **0.806** |
| hybrid nDCG@5 | 0.785 | **0.866** |

Swept 168 configs on TRAIN, reported HELDOUT for the winner; the gain generalized
(TRAIN blended 0.799 → 0.831 tracked HELDOUT 0.857 → 0.914).

## Observations

- **The vector leg dominates this corpus.** Pure vector (HELDOUT MRR 0.947) still
  edges even the tuned hybrid (0.921). Because `chunk_text` is a rich self-contained
  blurb (title + author + narrator + synopsis), the embedding captures the keyword
  signal too, so the lexical leg adds little. Tuning's win is mostly *not*
  over-weighting the weak lexical leg and *not* gating the strong vector leg.
- **The `POOL=97` win won't scale.** 97 = the whole library, so nothing is truncated
  — a free recall boost here, not on a larger corpus. The weight/gate changes are the
  transferable lesson.
- **Silver, not gold.** Every query is `review_status: needs_review`. Fill
  `~/out/eval/gold_core.template.json` with personal-memory queries (auto-merged),
  promote reviewed items, and keep the HELDOUT slice untouched by tuning.

## Next levers (re-run `eval.py` after each)

1. **Cross-encoder reranker** over the fused top-k — most likely lift given the strong vector recall.
2. **Larger embedding model** (768-d, e.g. bge-base), served the same way; update `VECTOR(384)` → new dim in `1_ingest.sql`.
3. **Surface metadata in retrieval** (pillar/series/author filters) for the topical queries.

> Results depend on the corpus, embedding model, and `HYBRID_*` knobs. Re-run after any change.
