```# Retrieval pipeline review

An outside review of the three retrieval legs and the fusion that combines them, with
every recommendation tied to a peer-reviewed paper or a first-party engineering source.

**Scope.** The Db2-native retrieval path: `src/hybrid_search/core.py`,
`scripts/1_ingest.sql`, `scripts/build_chunk_text.py`, and the evaluation that judges
them. The reranker is treated as what it is — a downstream stage outside Db2 — and is
deliberately never proposed as a fourth leg.

**Date:** 2026-08-11 · **Corpus at time of writing:** 92 books.

Findings are ordered by **what unblocks what**, not by expected size of gain. P1 is first
because until it is fixed, none of the improvements below can be shown to have worked.

---

## 1. What was measured

Everything in this document was read out of the repo, not recalled. Re-derive with:

```bash
# corpus + truncation figures
python - <<'PY'
import csv
rows=list(csv.DictReader(open('data/corpus.csv',newline='')))
L=sorted(len(r['chunk_text']) for r in rows); n=len(L)
print(f"rows={n} median={L[n//2]} p90={L[int(n*.9)]} max={L[-1]}")
print("over 1500 (ingest truncates):", sum(1 for x in L if x>1500))
print("over 2048 (build_chunk_text warns):", sum(1 for x in L if x>2048))
lost=sum(max(0,x-1500) for x in L); print(f"never embedded: {lost}/{sum(L)} = {100*lost/sum(L):.1f}%")
PY

# judged-set sizes
PYTHONPATH=src python scripts/export_judgments.py --list-sets
```

| measurement | value |
|---|---|
| corpus rows | 92 |
| `chunk_text` chars | min 134 · median 1483 · p90 2068 · max 3737 |
| books over the 1500-char embed cut | **44 of 92 (48%)** |
| corpus text never embedded | **21,165 of 133,330 chars (15.9%)** |
| human-judged topics | 6 total — `pooled_v1` 3, `shaikh-test-set1` 2, `stress_probe` 1 |
| human judgments | 90 (48 + 27 + 15) |
| synthetic golden set | 118 queries |

---

## P1 — The evaluation cannot currently detect the improvements you want to make

**This is the top finding, and it gates every other one.**

Six human-judged topics exist. The 118-query `golden_set` is synthetic — 106 of its
entries are "silver", generated and consistency-filtered.
`src/hybrid_search/metrics.py` returns point estimates only: there is no confidence
interval and no significance test anywhere in the file.

`docs/eval-framework-insights.md` already records the consequence, and states it
honestly: on the synthetic set hybrid wins, while on **both** human-judged sets vector is
well ahead of hybrid. The document's own honesty marker — "five judged queries cannot
settle whether hybrid or vector is better" — is correct.

The problem this creates for the work ahead: if you swap the embedding model and nDCG@5
moves from 0.62 to 0.68 across three topics, **that number cannot tell you whether
anything improved.** With six topics, per-query variance dominates.

**Recommendation.** Grow the judged pool substantially — the IR evaluation literature
treats ~50 topics as the working floor for a reliable comparison, and Voorhees & Buckley
quantify how error rate falls as topic-set size rises. Report effect size and a
confidence interval alongside any p-value, and apply correction when testing several
systems at once.

Also worth adopting: your qrels are pooled to a fixed depth, so unjudged documents exist.
Buckley & Voorhees show how incomplete judgments bias comparisons, and which measures
degrade most gracefully — relevant because a *new* embedding model will surface documents
the current pool never judged, which naive scoring counts as non-relevant by default.

> **Sources**
> - Voorhees & Buckley, *The effect of topic set size on retrieval experiment error*, SIGIR 2002 — topic-set size vs. error rate.
> - [Sakai, *Statistical Reform in Information Retrieval?*, SIGIR Forum 2014](http://www.sigir.org/wp-content/uploads/2020/06/p14.pdf) — report effect sizes and CIs, not p-values alone.
> - [Sakai, *Statistical Significance Testing in IR: An Empirical Analysis of Type I, Type II and Type III Errors*, SIGIR 2019](https://arxiv.org/pdf/1905.11096).
> - [Buckley & Voorhees, *Retrieval Evaluation with Incomplete Information*, SIGIR 2004](https://dl.acm.org/doi/10.1145/1008992.1009000) — bias from unjudged documents.

---

## P2 — Embedding truncation affects 48% of the corpus, and the docs understate it 4×

`docs/eval-results.md:58` states that "~11 books" have summaries longer than the embedding
cut. **The real number is 44 of 92.**

The discrepancy is a threshold mismatch between two files:

| file | threshold | books affected |
|---|---|---|
| `scripts/build_chunk_text.py:49` — the warning | `len/4 > 512` → **2048 chars** | 11 |
| `scripts/1_ingest.sql:90` — the actual `SUBSTR` | **1500 chars** | **44** |

So the monitoring reports on a threshold the ingest does not enforce, and has been
quietly under-reporting since the summaries were added. **15.9% of all corpus text is
never vectorized.** The median book (1483 chars) sits essentially on the cut, so the
corpus is maximally sensitive to it — a small growth in summary length moves many more
books over the line.

The BM25 index still covers the full text, so lexical retrieval is complete. This is a
dense-leg-only defect — which is a plausible partial explanation for why the vector leg
underperforms on content that lives deep in a summary, and worth testing directly.

**Recommendation, in order:**

1. **Fix the measurement bug first.** Have `build_chunk_text.py` and `1_ingest.sql` read
   one shared constant, so the warning can never again describe a different threshold
   than the ingest applies. Until this is done, you cannot trust your own reporting on
   whether the fix worked.
2. **Then remove truncation at the root** by moving to a longer-context embedding model,
   rather than mitigating it. `bge-small-en-v1.5` is a 2023 model: 384 dimensions, 512
   tokens. A model with an 8k context embeds every book in this corpus whole, with no
   `SUBSTR` at all, and no schema change — `chunk_id` stays the book id, so existing
   qrels, judgments and eval sets remain valid.

**Choosing the replacement.** Use MTEB and BEIR to shortlist, but heed BEIR's central
finding: **in-domain scores do not predict out-of-domain generalization**, and BM25
outperformed many neural models zero-shot. Leaderboard rank is a shortlist, not a
decision — the decision comes from §7's protocol run on your own corpus.

Chunk-per-row retrieval (split each book into passages, retrieve by max-pooling chunk
scores back to the book) is the textbook answer for genuinely long documents and remains
the right move if this corpus grows. It is deferred deliberately: it breaks the
`chunk_id` = book assumption that judgments, qrels and eval sets rely on. If you do take
it later, Anthropic's Contextual Retrieval is the strongest practical reference — a short
LLM-generated context prefix prepended to each chunk before embedding *and* before BM25
indexing, reducing failed retrievals by 49%, or 67% with reranking.

> **Sources**
> - [Anthropic, *Contextual Retrieval*](https://www.anthropic.com/engineering/contextual-retrieval) — chunk context; 49% / 67% failure reduction.
> - [Thakur et al., *BEIR: A Heterogenous Benchmark for Zero-shot Evaluation of IR Models*, NeurIPS D&B 2021](https://arxiv.org/abs/2104.08663) — in-domain ≠ out-of-domain; BM25 a strong zero-shot baseline.
> - [Muennighoff et al., *MTEB: Massive Text Embedding Benchmark*](https://arxiv.org/abs/2210.07316) — shortlisting.

---

## P3 — The fusion design is sound; the gates are dead and the normalization is query-local

**First, what is right.** `core.py`'s docstring rejects plain RRF on the grounds that it
fuses on rank alone and discards each leg's confidence. **The literature agrees with
you.** Bruch, Gai & Ingber compared exactly this choice and found that a convex
combination of normalized scores outperforms RRF both in-domain and out-of-domain, that
RRF is sensitive to its parameters (contrary to its reputation), and that the convex
weight is sample-efficient to tune. This is a case where the code's stated reasoning is
backed by a peer-reviewed result — keep it, and cite it.

Two genuine defects:

**The gating is switched off.** `HYBRID_VEC_GATE=0.0` and `HYBRID_LEX_GATE=0.0` in both
`.env.example` and `core.py`. `_normalized()` (`core.py:189`) emits
`CASE WHEN MAX(s) OVER () < 0.0 THEN 0 …`, and no score is below zero — so the branch
never fires. The module docstring describes a "GATED, SCORE-NORMALIZED fusion" and step 3
of its own numbered explanation is currently inert. Either tune the gates against real
judgments (they were designed for exactly the failure the eval already documents — bare
narrator names embedding to noise, e.g. *"walter dixon"* at vector rank 36) or remove the
claim from the docstring. Documented behavior that is switched off is worse than absent
behavior, because it stops anyone looking.

**Normalization is query-local.** `s / MAX(s) OVER ()` divides by the maximum *within
this query's candidate pool*, so a score of 1.0 means "best thing found for this query",
not "good". Scores are therefore not comparable across queries, which matters the moment
you set a threshold, a gate, or a confidence cutoff. Bruch et al.'s consolation is that
for *learning the convex weight*, the specific linear normalization is largely
rank-equivalent — so this is not a ranking bug within one query. It is a problem for
anything cross-query, including the gates above.

**One flag, not a recommendation:** if the corpus grows past `HYBRID_POOL=100`, the pool
stops being exhaustive (it currently exceeds the 92-row corpus, so both legs see
everything). At that point `FETCH APPROX` also starts mattering — measure ANN recall
against an exact scan before trusting the vector leg at scale.

> **Source**
> - [Bruch, Gai & Ingber, *An Analysis of Fusion Functions for Hybrid Retrieval*, ACM TOIS 41(4), 2023](https://dl.acm.org/doi/10.1145/3596512) · [arXiv:2210.11934](https://arxiv.org/abs/2210.11934).

---

## P4 — The lexical leg is a bag of OR'd terms with no structure

`core.keywords()` (`core.py:127`) drops English stopwords and joins every remaining word
with ` OR `. That is the entire query model. It means:

- **No phrase matching.** *"the cue routine reward habit loop"* is six independent terms;
  a book containing "routine" and "reward" in unrelated sentences competes with the book
  that contains the actual phrase.
- **No field weighting.** `chunk_text` concatenates title, authors, narrators and a
  description up to 3,737 chars into one undifferentiated field
  (`scripts/build_chunk_text.py:25`). A query term matching the **title** scores the same
  as one matching a passing mention 3,000 characters into a summary. BM25's length
  normalization partly compensates, but it cannot recover a distinction the index never
  encoded.
- **No required terms.** Every term is optional, so precision rests entirely on IDF.

BM25F — the field-weighted extension of BM25 — is the standard, well-understood answer,
and is what powers field-aware production search. Db2 Text Search supports both **phrase
search** and **term boosting** (integer weights 0–1000, default 100), so a weighted,
phrase-aware query is expressible without leaving Db2 and without a second engine.

**Recommendation.** Boost title/author/narrator terms above description terms, and try
the query's full phrase as a boosted clause OR'd with the current bag-of-terms fallback.
Test it as its own arm under §7 — this is cheap, Db2-native, and independent of the
embedding swap.

> **Sources**
> - [Robertson & Zaragoza, *The Probabilistic Relevance Framework: BM25 and Beyond*, Foundations and Trends in IR 3(4), 2009](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf) — BM25F and field weighting.
> - [IBM, Db2 Text Search argument syntax](https://www.ibm.com/docs/en/db2/11.5.x?topic=indexes-text-search-argument-syntax) · [CONTAINS scalar function](https://www.ibm.com/docs/en/db2/11.5.x?topic=functions-contains).

---

## P5 — No document expansion

Vocabulary mismatch is the lexical leg's structural blind spot, and the eval already
quantifies it: on semantic-type queries lexical MRR falls to 0.476 while vector carries
them at 0.802 (`docs/eval-results.md`). Document expansion attacks this at **index**
time — generate the questions a document answers, append them to the indexed text — so
query latency is untouched and search stays Db2-native. Reported gains are roughly 15%
over a BM25 baseline.

You already have the machinery: a local Qwen generation server in
`scripts/query-understanding/`, currently used for the query-side path that is off by
default (`QU_MODE=off`).

**Caveat, and it is important.** Naively generated queries inject noise as well as
signal. *Doc2Query--: When Less is More* shows that a substantial share of generated
queries are harmful and that filtering them materially improves results. Treat generation
as producing *candidates* to be filtered, not text to be trusted.

> **Sources**
> - [Nogueira et al., *Document Expansion by Query Prediction*, arXiv:1904.08375](https://arxiv.org/pdf/1904.08375).
> - [Nogueira & Lin, *From doc2query to docTTTTTquery*](https://cs.uwaterloo.ca/~jimmylin/publications/Nogueira_Lin_2019_docTTTTTquery-v2.pdf).
> - [Gospodinov, MacAvaney & Macdonald, *Doc2Query--: When Less is More*, ECIR 2023](https://arxiv.org/pdf/2301.03266) — filtering generated queries.

---

## P6 — The reranker is built, evaluated, and switched off

`src/hybrid_search/rerank.py` exists and `RERANK_ON=0`. In the literature this is the
single largest quality step available: Nogueira & Cho's BERT cross-encoder re-ranker took
the top of the MS MARCO passage leaderboard, beating the previous state of the art by
**27% relative in MRR@10** — over an already-neural baseline, not over BM25, so the gain
against a plain first-stage ranker is larger still. Anthropic's numbers show reranking
taking failure reduction from 49% to 67% on top of an already-improved retriever.

**This does not change the project's boundary, and should not.** The reranker runs
outside Db2 and consumes the fusion's output; it is a downstream stage, not a competitor
to the three legs. Reporting it as a fourth leg would make the three-leg comparison
dishonest, since it would be scoring a pipeline that includes the other three.

**Recommendation.** Keep it out of the leg comparison; report it as a clearly separate
downstream row — "hybrid → reranked" — so its contribution is visible without
contaminating the Db2-native claim. Note also that the standard recipe retrieves a *deep*
candidate set before reranking (Anthropic use top-150 → top-20); `RERANK_N=20` is shallow
by comparison and likely leaves quality on the table.

> **Sources**
> - [Nogueira & Cho, *Passage Re-ranking with BERT*, arXiv:1901.04085](https://arxiv.org/abs/1901.04085) — +27% relative MRR@10 over the previous SOTA on MS MARCO passage.
> - [Anthropic, *Contextual Retrieval*](https://www.anthropic.com/engineering/contextual-retrieval) — retrieve-deep-then-rerank; 67% failure reduction.

---

## 7. How to measure whether any of this helped

The point of this section is that **"nDCG went up" is not evidence** at your current
eval-set size. This is the protocol that turns a change into a defensible claim.

### Make A/B a SQL switch, not a re-ingest

Add the new embedding as a **second VECTOR column** on `MYSCHEMA.CHUNKS` — e.g.
`embedding_v2 VECTOR(N, FLOAT32)` alongside the existing `embedding` — each with its own
vector index, and register the new model as a second `EXTERNAL MODEL`.

Both models are then queryable **in the same database, over identical rows, at the same
instant**. No re-ingest between arms, no window in which a corpus edit or a re-fetched
description contaminates the comparison, and instant rollback. Retire the old column only
once the new one has won. This costs one column and one index on a 92-row table.

### The protocol

1. **Freeze the baseline before touching anything.** Run `scripts/eval.py` across every
   named set and commit the output as a dated file. A baseline captured *after* you start
   changing things is not a baseline.
2. **Hold the eval set fixed across arms.** Same qrels, same topics. The change under
   test must be the only thing that varies.
3. **Compare paired per-query scores, not set averages.** `metrics.py` currently returns
   means (`score_block`); a paired test needs the per-query vector. This is a small
   addition and it is a prerequisite for steps 4–6.
4. **Report effect size and a confidence interval**, via paired bootstrap or randomization
   over per-query differences — not a bare point estimate, and not a p-value alone (P1).
5. **Re-tune the fusion weights after re-embedding.** `W_LEX=0.3 / W_VEC=0.7` were fit by
   5-fold CV *against the current model*. A new vector leg invalidates them, and judging a
   re-embedded system on stale weights understates the gain. Bruch et al. is the citation
   for this being cheap: the convex weight is sample-efficient to re-fit.
6. **State the minimum detectable effect.** With six topics, say plainly what the set can
   and cannot resolve, and do not report a winner the data cannot support.

### A targeted prediction for the truncation fix

Aggregate movement is weak evidence — many things move an aggregate. Instead, **split the
corpus by whether a book was truncated** (44 affected, 48 not) and report retrieval
quality on each subset separately.

If removing truncation is what helped, **the gain concentrates in the 44 affected books
and is near zero on the other 48.** That is a falsifiable prediction. If quality rises
uniformly across both subsets, the improvement came from the new model being better in
general, not from fixing truncation — a different (and still good) result, but a
different claim, and you should not report the one as the other.

### Re-pool after switching models

A new embedding model surfaces documents the existing pool never judged, and unjudged
documents are scored as non-relevant by default — which systematically penalizes the new
arm for finding things nobody has looked at yet. Re-pool the affected topics through the
Label tab before drawing conclusions (P1's Buckley & Voorhees).

---

## 8. What not to do

Recorded so these are not revisited:

- **Do not switch to RRF.** Your stated reason for rejecting it is supported by Bruch et
  al. (P3), which found convex combination superior in-domain and out-of-domain.
- **Do not make the reranker a fourth leg.** It consumes the fusion's output and runs
  outside Db2 (P6).
- **Do not tune weights or gates on `golden_set`.** It is consistency-filtered and biased
  toward whatever generated it; `docs/eval-framework-insights.md` already demonstrates it
  disagreeing with human judgments about which leg wins (P1).
- **Do not trust an MTEB rank as a model decision.** BEIR's core finding is that
  in-domain scores do not predict out-of-domain behavior (P2). Shortlist with the
  leaderboard, decide with §7.

---

## Summary

| # | Finding | Effort | Blocked by |
|---|---|---|---|
| **P1** | Eval cannot detect the changes you want to make — 6 judged topics, no CIs, no significance test | High (judging) | — |
| **P2** | 48% of corpus truncated before embedding; docs understate it 4× | Low (bug) + Medium (model swap) | P1 to verify |
| **P3** | Gates are inert; normalization is query-local. Fusion choice itself is sound and literature-backed | Low | P1 to tune |
| **P4** | Lexical leg has no phrases, no field weighting, no required terms | Medium | P1 to verify |
| **P5** | No document expansion; ~15% BM25 gains reported, needs filtering | Medium | P1 to verify |
| **P6** | Reranker built and switched off; largest single-stage gain in the literature | Low | — |

The through-line: **P1 gates everything.** The fastest path to a defensible improvement
is to judge more topics first, fix the truncation measurement bug (an afternoon), then run
the model swap through §7's protocol with the truncated/untruncated split as the test of
whether the fix did what you think it did.
