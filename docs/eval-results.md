# Evaluation Results — Hybrid Search

Search-quality results produced by the evaluation harness.

- **Reproduce:** `DB2_HOST=local python scripts/eval.py`
- **Golden eval set** (relevance judgments / *qrels*): [scripts/eval.py](../scripts/eval.py)
  — 16 queries, each paired with its known-relevant chunk(s)
- **Corpus:** IBM Db2 12.1.5 LLM-integration reference (101 chunks)
- **Embeddings:** local **bge-small-en-v1.5** (384-dim) via llama.cpp / Db2
  `PROVIDER OPENAI` — see [local-embeddings.md](local-embeddings.md). Queries carry
  bge's retrieval instruction; passages are embedded raw.
- **Date:** 2026-07-07
- **Verdict:** ✅ PASS

Each number is the **position of the correct answer** in that mode's results
(1 = top, lower is better). **—** = not found in the top 10.

## Scores by mode

| mode | MRR | Recall@5 | Hits@1 |
|---|---|---|---|
| lexical (keyword) | 0.511 | 0.688 | 0.375 |
| vector (semantic) | 0.669 | 0.885 | 0.500 |
| **hybrid (fusion)** | **0.807** | **0.938** | **0.688** |

Plain-English (hybrid mode): correct answer at **#1 in 11/16 (69%)**, in the
**top 5 in 16/16 (100%)**, and **never missed** (0/16). Keyword-only got #1 in
6/16; vector-only in 8/16 — the fusion is still clearly best.

## Per-query results

| # | Question | Best suited to | Lex | Vec | Hyb |
|---|---|---|---|---|---|
| 1 | `42615` | keyword (code) | 1 | 1 | 1 |
| 2 | `42613` | keyword (code) | 1 | 5 | 1 |
| 3 | `REASONING_EFFORT` | identifier | — | 1 | 1 |
| 4 | `REPETITION_PENALTY` | identifier | — | 1 | 1 |
| 5 | `42601` | keyword (code) | 5 | 4 | 1 |
| 6 | `38555` | keyword (code) | 1 | — | 1 |
| 7 | how can I make the model stop generating at a certain phrase | vector | 4 | 2 | 1 |
| 8 | how do I turn text into vectors | vector | 2 | 1 | 1 |
| 9 | what controls the randomness of the output | vector | 3 | 2 | 3 |
| 10 | limit the maximum length of the generated text | vector | 2 | 4 | 2 |
| 11 | how long can text generation run before timing out | vector | — | 1 | 4 |
| 12 | what privilege is needed to use TO_EMBEDDING | hybrid | 4 | 2 | 2 |
| 13 | how do I change the API key on an existing model | hybrid | 1 | 1 | 1 |
| 14 | how do I transfer ownership of a model to another user | hybrid | 1 | 2 | 1 |
| 15 | how do I register an external model | hybrid | 7 | 1 | 3 |
| 16 | how do I drop an external model | hybrid | 1 | 1 | 1 |

## Summary

- ✅ correct answer at #1 (hybrid): **11 / 16**
- ⚠️ correct answer in top 5, not #1: **5 / 16** (#9, #10, #11, #12, #15)
- ❌ missed entirely: **0 / 16**

## Observations

- **Fusion adds real value** — #5, #7, #12, #14 rank better in hybrid than in
  either single leg; hybrid MRR (0.807) beats lexical (0.511) and vector (0.669).
- **Vector recall is strong** — bge finds a relevant chunk in the top-5 for 15/16
  queries. bge's query instruction (applied to queries only) is what lifts recall.
- **The gate barely fires with bge.** bge cosine similarities cluster high
  (~0.59–0.69) even for bare error codes (42615 → 0.60), so `HYBRID_VEC_GATE`
  can't cleanly separate "confident" from "guessing" the way it did for a
  wider-spread model. The vector leg therefore participates on nearly every query
  — sometimes helping (#5), sometimes nudging a keyword-perfect answer down (#11).
- The imperfect cases (#9–#12, #15) trace to **fragmented chunks + a small
  384-d model**, plus that flat gate.

## Comparison to the previous model

The earlier run used watsonx.ai `all-MiniLM-L6-v2` and scored hybrid
**MRR 0.887 / Recall@5 0.969 / Hits@1 0.812**. Switching to local bge-small
traded a little top-rank accuracy (Hits@1 0.812 → 0.688) for **better vector
recall** (0.812 → 0.885) — and, more importantly, no API keys, no egress, and no
per-call cost. On a 16-query set this is a 1–2 query swing; judge on your own
corpus.

## Next levers (re-run `DB2_HOST=local python scripts/eval.py` after each)

1. **Better chunking** — merge heading fragments and prepend section context.
2. **Larger embedding model** — a 768-d model (e.g. bge-base / gte-base), served
   the same way; update `VECTOR(384)` → the new dim in `4_ingest.sql`.
3. **Cross-encoder reranker** — rerank the fused top-k.

> Notes: these results depend on the corpus, the embedding model, and the fusion
> knobs (`HYBRID_*`). Re-run after any change to refresh this report.
