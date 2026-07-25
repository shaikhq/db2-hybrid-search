# Experiment: LLM as a re-ranker vs. a cross-encoder re-ranker

- **Date:** 2026-07-25
- **Corpus:** personal audiobook catalog (92 books)
- **Status:** concluded — LLM re-ranking not adopted

## Question

A popular strategy in RAG, and Agentic RAG especially, is to use an LLM to re-rank the
search results and pick the best matching one. I wanted to try this out on my own use
case: can a small, local LLM beat my existing cross-encoder re-ranker, or even the
hybrid-search baseline?

## Use case and existing setup

I run a hybrid search on my audiobook catalog. It combines results from lexical search
and vector search and fuses them with a score-based fusion algorithm. On top of that I
have a re-ranker, and a golden evaluation set of 20 queries with their known answer
chunks. The re-ranker was already doing a good job, often pushing more accurate results
above plain hybrid search. So the question was whether a small, local LLM could beat it.

## Strategies compared

All three select their #1 result from the **same top-10 hybrid candidates**, so it is a
controlled, apples-to-apples comparison:

1. **Hybrid search + fusion** — the baseline.
2. **Cross-encoder re-ranker** — re-scores and reorders the top 10 (its own ranking).
3. **Agentic LLM** — reads the top 10, reasons over them, and returns its rank list /
   best pick. The prompt was a re-ranking instruction template with a placeholder for the
   search results, plus anti-hallucination rules; the chosen ID is validated against the
   candidate set so it cannot return a result that was not in the list.

## Models (all small, quantized, running locally on CPU)

| role | model | notes |
|---|---|---|
| embedding | `bge-small-en-v1.5` | 384-dim, q8_0 |
| re-ranker | `bge-reranker-v2-m3` | cross-encoder, Q4_K_M |
| LLM | `Qwen2.5-3B-Instruct` | Q4_K_M (small, quantized — not a sophisticated LLM) |

## Method and metric

For each of the 20 queries I run hybrid search, take the top 10 results, and send them to
both the re-ranker and the LLM to produce their rankings. Then I check the **top matching
result (the number one position)**: how many times was the correct answer found at rank 1?
Hybrid search is the baseline; I check the same for the re-ranker's and the LLM's #1.

This is **top-1 accuracy (Hits@1)**: in the first hit, the correct answer was found. The
gold answer was present in the shared top-10 for **all 20 queries**, so this measures
*ranking*, not retrieval recall.

## Results

| strategy | Top-1 accuracy (Hits@1) | reproducible? |
|---|---|---|
| **Cross-encoder re-ranker** | **0.95** (19/20) | yes — identical every run |
| Hybrid fusion (baseline) | **0.90** (18/20) | yes — identical every run |
| Agentic LLM | **0.75–0.85** (15–17/20) | no — varies run to run |

## Additional observations

- The LLM score is a range because it was **not stable**:
  - **Non-deterministic even at temperature 0** — repeated identical runs gave different
    scores (e.g. 0.75 then 0.85).
  - **Prompt-sensitive** — a terse prompt scored ~0.20–0.30; a richer "reason step by
    step and do not hallucinate" prompt scored ~0.75–0.85.
- Hybrid search and the cross-encoder re-ranker were **deterministic** — the same score on
  every repeat.
- The LLM's misses clustered on **exact-title and bare-name queries**, where surface-token
  matching (lexical / cross-encoder) does well but the small model tends to pick a
  thematically similar but wrong book.

## Conclusion

For this use case, I am not going to add an LLM re-ranking leg. The LLM did not do a
better job than the baseline — it did not even beat hybrid search (0.90). The re-ranker,
on the other hand, did improve on the baseline (0.95). I did not find evidence that the
LLM helps here, so I did not add this LLM leg for refining the results from hybrid search.

## Caveats

- All models are small, quantized, and running locally on CPU; a larger or hosted LLM
  might change the outcome.
- This is my own dataset and my own evaluation set (20 held-out known-item queries).

## Open question

Has anyone compared a re-ranker against an LLM as a re-ranker on their own data? Did the
LLM ever beat the re-ranker?
