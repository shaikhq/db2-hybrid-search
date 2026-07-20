# Evaluation Results — Hybrid Search (audiobook corpus)

Search-quality results from `scripts/eval.py` against the shipped audiobook
corpus (one row per book; `chunk_text` = title + authors + narrators + description).

- **Reproduce:** `DB2_HOST=local PYTHONPATH=src python scripts/eval.py` (or `pip install -e .` then drop `PYTHONPATH`)
- **Golden eval set:** [`data/eval/golden_set.json`](../data/eval/golden_set.json) — **111 queries**, stratified into TRAIN (90) / **HELDOUT (21, ~19%)**. known_item queries have one gold book; topical queries list all qualifying books. Ships with the repo, so these numbers are reproducible from a clean clone.
- **Corpus:** 92 audiobooks in Db2 `MYSCHEMA.CHUNKS`.
- **Embeddings:** local **bge-small-en-v1.5** (384-dim) via llama.cpp / Db2 `PROVIDER OPENAI` — see [../install/README.md](../install/README.md). Queries carry bge's retrieval instruction; passages embedded raw.
- **Fusion knobs:** `HYBRID_W_LEX=0.1 W_VEC=0.9 VEC_GATE=0.0 LEX_GATE=0.0 POOL=100` — the shipped defaults in `.env.example`, `core.py`, and `2_search.sql`.
- **Date:** 2026-07-20

Metrics: **known_item →** MRR, Hits@1. **topical →** Recall@5, nDCG@5.

## HELDOUT — the honest number (never tuned on)

| leg | MRR | Hits@1 | Recall@5 | nDCG@5 |
|---|---|---|---|---|
| lexical | 0.817 | 0.778 | 0.778 | 0.716 |
| vector | 0.839 | 0.833 | 0.917 | **0.944** |
| **hybrid** | **0.847** | **0.833** | **0.917** | 0.926 |

## ALL 111 queries

| leg | MRR | Hits@1 | Recall@5 | nDCG@5 |
|---|---|---|---|---|
| lexical | 0.836 | 0.792 | 0.552 | 0.590 |
| vector | 0.882 | 0.833 | **0.678** | **0.738** |
| **hybrid** | **0.898** | **0.854** | 0.651 | 0.720 |

## Diagnostic — known_item MRR by query type

| query_type | lexical | vector | hybrid |
|---|---|---|---|
| keyword | **0.989** | 0.887 | 0.943 |
| semantic | 0.246 | **0.681** | 0.619 |
| mixed | 0.890 | **0.958** | **0.958** |

This is the eval validating itself, and it's the most informative table here:

- **semantic** queries score **0.246** on the lexical leg — they defeat keyword
  matching by construction, and the vector leg rescues them (0.681).
- **keyword** queries invert it: the vector leg drops to **0.887** while lexical
  scores 0.989. These are bare narrator-name lookups where the embedding drifts
  (e.g. *"walter dixon"* → vector rank 15, *"julie brierley"* → rank 40) and exact
  token matching is the only thing that works.
- **hybrid** is never the best on any single row — but it is never the *worst*
  either, and it wins the aggregate. That is precisely the claim: each leg has a
  blind spot, and fusion covers both.

## An important caveat about this eval set

Until 2026-07-20 this table could **not** demonstrate the project's thesis. Every
one of the original keyword queries scored ~0.99 on *both* legs, so the eval was
blind to the leg divergence the demo tab visibly reproduces. Measured on that set,
hybrid merely *tied* pure vector — which argued for deleting the lexical leg.

Five queries (`source: leg_discriminating` in the golden set) were added to cover
the case the set was missing: bare narrator names, where the vector leg genuinely
fails and lexical rescues it. Each was verified against the live engine before
being added; none are synthetic.

The lesson generalizes: **an eval set that doesn't contain the queries where your
components disagree will tell you to delete a component you need.** Only five such
queries exist in a 92-book corpus, so the honest reading is that the vector leg
does most of the work here and the lexical leg is *insurance* — cheap, and the only
thing that answers an exact-token lookup.

## Observations

- **The vector leg carries this corpus.** `chunk_text` is a rich self-contained
  blurb (title + author + narrator + synopsis), so the embedding already captures
  much of the keyword signal. Hence `W_VEC=0.9`.
- **The weight is corpus-specific and was re-derived, not guessed.** A 5-fold-CV
  sweep over α = `W_VEC/(W_LEX+W_VEC)` put the optimum at α ∈ [0.9, 1.0] (1-SE
  band); α=0.9 is the one-standard-error pick — statistically tied with pure vector
  on aggregate MRR, but retaining the lexical leg that the keyword row shows you need.
- **`POOL=100` won't scale.** It exceeds the 92-book corpus, so each leg is
  exhaustive and nothing is truncated — a free recall boost here, not on a larger
  corpus. The weight/gate settings are the transferable lesson.
- **Silver, not gold.** The 106 original queries are `review_status: needs_review`.
  Fill [`data/eval/gold_core.template.json`](../data/eval/gold_core.template.json)
  with personal-memory queries (auto-merged), promote reviewed items, and keep the
  HELDOUT slice untouched by tuning.

## Next levers (re-run `eval.py` after each)

1. **Cross-encoder reranker** over the fused top-k — most likely lift given the strong vector recall.
2. **Larger embedding model** (768-d, e.g. bge-base), served the same way; update `VECTOR(384)` → new dim in `1_ingest.sql`.
3. **Grow the discriminating slice.** Five leg-divergent queries is thin. More exact-token
   cases (IDs, series positions, publishers) would sharpen the keyword row.
4. **Surface metadata in retrieval** (pillar/series/author filters) for the topical queries.

> Results depend on the corpus, embedding model, and `HYBRID_*` knobs. Re-run after any change.
