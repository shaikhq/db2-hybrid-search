# Building a retrieval evaluation set you can actually trust

Source material for a talk/post. Audience: engineers building hybrid search (lexical +
vector) who need an evaluation set they believe.

Every number below was read out of this repo on the date of writing and can be
re-derived with the command shown. **Re-run them before publishing** — the judged set
grows, and stale numbers are the fastest way to lose credibility.

```
PYTHONPATH=src python scripts/export_judgments.py --list-sets
DB2_HOST=local PYTHONPATH=src python scripts/eval.py data/eval/sets/pooled_v1.json
DB2_HOST=local PYTHONPATH=src python scripts/eval.py          # the synthetic deck
```

**Current state:** 92-document corpus. 5 queries fully judged, 75 individual judgments,
across 3 named test sets. Plus an older 118-query synthetic set kept deliberately apart.

---

## The finding that motivates the whole thing

Two evaluation sets over the same corpus and the same three retrievers, disagreeing about
which retriever is best:

| set | how it was built | lexical | vector | hybrid |
|---|---|---|---|---|
| `golden_set` (118 q) | machine-generated, binary, 103/118 known-item | MRR **0.867** | **0.898** | **0.909** |
| `pooled_v1` (3 q) | human-judged, graded, 100% topical | nDCG@5 0.470 | **0.823** | 0.622 |
| `shaikh-test-set1` (2 q) | human-judged, graded, 100% topical | nDCG@5 0.532 | **0.814** | 0.587 |

On the synthetic set, hybrid wins — which is this project's headline claim. On both
human-judged sets, **vector is well ahead of hybrid**.

That is not noise, and it is not (necessarily) a bug in the fusion. It is what happens
when two eval sets are *constructed differently*. The rest of this document is the design
decisions that make that difference visible instead of invisible.

**Honesty marker:** five judged queries cannot settle whether hybrid or vector is better.
What the comparison does establish is that **the construction method of your eval set
determines the answer you get** — which is the point worth making.

---

## Stage 1 — Where test queries come from

### 1. Machine-generated query sets are biased by their own filter, and the bias favours whatever built them

**How most teams do it today:** generate queries with an LLM from each document, keep the
ones where the source document is retrievable. That is *consistency filtering* — the
Promptagator (Dai et al., 2022) and InPars (Bonifacio et al., 2022) recipe, and it is a
good recipe. This repo does exactly that in `scripts/filter_eval_candidates.py`.

**Where it breaks:** the keep-only-if-retrieved rule *selects for queries the current
system already answers*. It cannot produce a query your retrievers both miss, because
such a query is discarded at generation time. And because each query is generated from
one source document, the result is overwhelmingly **known-item**: 103 of 118 entries here
(`data/eval/golden_set.json`). Known-item queries are scored with MRR and Hits@1, which
reward putting one right answer first — exactly what fusion is good at.

**What you gain by noticing:** you stop reading a synthetic set as a measure of quality
and start reading it as a *regression harness* — good for "did I break something?",
weak for "which approach is better?". Note the split in your own repo:
`golden_set` is 103 known-item / 15 topical; both human sets are 100% topical. They are
not measuring the same capability.

### 2. Type the queries yourself, from real information needs, before you look at results

The five judged queries here are things a person would actually say — *"I am looking for a
book on public speaking"*, *"how can I become effective communicator"* — typed into the
labeling tool with no target book in mind. That is the opposite of the generated set,
where a target document existed before the query did.

The cost is real: this is slow, and after a full day of work there are five of them. Say
so out loud when you present it. The value is that nothing about the query was chosen to
be findable.

### 2b. Let a model PROPOSE topics — but only from the subject areas, and never filter by what retrieves

A day per five topics does not reach the ~50 the evaluation literature wants. The Label
tab's **Generate topics** control closes that gap without giving up what §1 and §2 argue
for, by keeping the two properties that actually mattered:

- **Generation sees the collection's subject areas, never a book's text.** The prompt is
  built from the `genres`/`pillar` columns only. No target document exists before the
  query, so the query cannot inherit one document's vocabulary — which is what made
  `golden_set` 103/118 known-item.
- **Retrieval is never run during generation.** No candidate is dropped for being hard to
  find. That rule is what separates this from the consistency filtering in §1, and it is
  enforced by a test that makes `core.lexical`/`vector`/`hybrid` raise and requires
  generation to succeed anyway (`tests/test_topicgen.py`).

Everything after generation is unchanged: a person edits or discards every candidate, and
every relevance judgment is still made by hand against a pooled, rank-discarded list.
**The model proposes topics; it never judges them.** That distinction is the whole reason
this is safe to adopt — the reported risk in synthetic collections is concentrated in LLM
*judges*, which inflate scores and favour systems resembling themselves.

What it costs, stated plainly:

- Generated queries are **longer and more uniform** than real ones. The prompt explicitly
  asks for a length mix including 2-4 word fragments, and the review step lets you shorten
  them, but this is mitigation, not elimination.
- LLM-written query variants **do not cover the full spread** a group of humans produces.

Two habits keep this honest. **Provenance is recorded per topic** (`origin`:
`human`/`llm`/`llm_edited`, with the model's original wording kept when you edit it), and
the exporter reports the mix in `manifest.json` — so a set that blends both says so.
**Discards are logged on the set**, because the ✕ is itself a filter: quietly deleting the
candidates you dislike is the same failure as keeping only the ones your retriever already
answers, just performed by hand.

And the check that settles it for *this* corpus rather than in general: once ~15 generated
topics are judged, score the legs on the LLM-origin subset and the hand-typed subset
separately. If they disagree about which leg wins — as `golden_set` and the human sets
already do above — that belongs in this document, not smoothed away.

> Evidence: [Alaofi et al., *Can Generative LLMs Create Query Variants for Test
> Collections?*, SIGIR 2023](https://dl.acm.org/doi/10.1145/3539618.3591960) — LLM queries
> written from information-need backstories reach 71.1% pool overlap with human queries at
> depth 100, while not capturing their full variety. [Rahmani et al., *Synthetic Test
> Collections for Retrieval Evaluation*](https://arxiv.org/abs/2405.07767) and [*Towards
> Understanding Bias in Synthetic Data for Evaluation*, CIKM
> 2025](https://arxiv.org/pdf/2506.10301) — synthetic collections rank systems in
> moderate-to-high agreement with human-based evaluation; the leniency and self-preference
> problems they document are properties of LLM *judging*, which this design does not use.

---

## Stage 2 — Building the candidate pool

### 3. Pool from every retriever, then throw the ranking away

For each query, take the top-k from *each* retriever, union them, dedup, and **discard
rank and score entirely**. This is TREC pooling, and the rank-discarding is the part
people skip.

In this repo, `build_pool()` in `ui/api.py` returns bare chunk ids. The judging API never
emits a rank, a score, or which leg surfaced a document — and there is a test asserting
that the wire format carries no such field, not merely that the renderer hides it.

**Why it matters:** if you can see that the vector leg ranked something #1, you will judge
it more generously. That is documented assessor behaviour (order and threshold priming —
Eisenberg & Barry 1988; Scholer, Turpin & Sanderson, SIGIR 2011). If your pool leaks rank,
your judgments encode your current system's opinion, and you have built a benchmark that
can only ever agree with you.

### 4. Seed the shuffle on the query so a resumed session is stable

The pool is shuffled with `random.Random(md5(query))`. Deterministic, so re-opening a
half-judged query presents the same cards in the same places. A freshly random order each
time makes "the next unjudged item" jump around and quietly wastes the assessor's
attention on re-reading.

Small decision; it is the difference between a tool you finish 20 queries in and one you
abandon at 6.

### 5. Be explicit about pool depth — it decides how reusable your collection is

Here: depth 10 per leg, 2 legs, giving 12–17 unique documents per query, **about 16% of a
92-document corpus**. TREC pools are typically depth-100 across dozens of systems.

`trec_eval` treats unjudged documents as non-relevant. So a *future* retriever that
surfaces a genuinely relevant document neither of your current legs pooled gets penalised
for finding it. This is pool bias (Zobel, 1998; and the motivation for bpref — Buckley &
Voorhees, SIGIR 2004). Record pool depth and contributing legs as metadata —
`data/eval/sets/manifest.json` does — and re-pool when you add a materially different
retriever.

---

## Stage 3 — Collecting judgments

### 6. Grade relevance; do not judge it binary

nDCG is *defined* on graded gain (Järvelin & Kekäläinen, TOIS 2002). With binary
judgments it degenerates into rank-weighted recall, and a perfect answer scores identically
to a marginally on-topic one.

**The evidence is in this repo's own numbers.** On `shaikh-test-set1`:

| | Recall@5 | nDCG@5 |
|---|---|---|
| vector | 0.444 | **0.814** |
| hybrid | **0.500** | 0.587 |

Hybrid retrieves *more* relevant books in the top 5. Vector puts the *highly relevant* ones
higher. **A binary eval set would have shown hybrid winning and hidden the ordering
difference completely.** That single table is the argument for grading.

Scale used: 3 points — `irrelevant` 0, `relevant` 1, `highly_relevant` 2 — not TREC Deep
Learning's 4. A solo assessor over hundreds of judgments stays more self-consistent with
fewer levels, and this domain has no equivalent of DL's "answers but buried in extraneous
information" distinction. Judge graded, binarize later; you can always collapse grades
down and never recover them from binary.

### 7. Make the keystroke *be* the grade

`2` = highly relevant, `1` = relevant, `0` = not relevant, `s` = skip. Nothing to
memorise, and the scale stays in front of the assessor while judging. At ~15 documents ×
20 queries, mouse travel is the difference between one sitting and three.

### 8. A judged item collapses in place — it never disappears

What "relevant" means for a query is calibrated *while* judging it; the 12th document
often reveals the 3rd was borderline. If judged cards vanish, you cannot recalibrate, and
your own inconsistency is baked into the gold set. Keep them visible, collapsed, and
freely re-gradable with one keypress.

This is the practical answer to Voorhees (2000): assessors disagree, including with
themselves — but system *rankings* stay stable. Make correction cheap rather than
pretending it is unnecessary.

### 9. "Skip" is a gap, not a zero

Skip means *seen, no judgment*. It counts toward "have I worked through this pool?" and is
**omitted from the qrels file entirely**. Folding skips into "not relevant" would fabricate
judgments you never made. Track two numbers — decided/total and skipped — because they
answer different questions.

---

## Stage 4 — Turning judgments into a test collection

### 10. Three artifacts, joined by a stable id — not one blob

A test collection is **corpus + topics + qrels** (the Cranfield model), in separate files
joined by a `qid`:

```
data/eval/topics/<set>.tsv     q001 <TAB> managing stress
data/eval/qrels/<set>.qrels    q001 0 19 2        ← TREC qrels: qid, unused 0, docid, grade
data/eval/sets/<set>.json      the eval deck the app itself loads
```

Emit real TREC qrels and `trec_eval`, `pytrec_eval` and `ir_measures` work on your data
with no adapter. It costs about fifteen lines.

**The id is the load-bearing part.** Query *text* is a display field. Key your store by
text and retyping "Managing Stress" strands the judgments attached to "managing stress".
`_qid_for()` in `ui/api.py` normalises case and whitespace to resolve back to the existing
qid, and the qid is what every qrels line references.

### 11. Never merge human and machine judgments into one file

They are separate assessment efforts with different reliability. Merge them and you can no
longer report either alone — and "Recall@5 over 20 human-verified queries" is a far
stronger claim than "over 118 mostly-unreviewed generated ones".

`scripts/export_judgments.py` does not touch `golden_set.json` by default; combining is an
explicit `--merge-golden` opt-in. If you want a combined view, compose it **at load time**,
not at storage time. This is how TREC and BEIR are organised, and it is what made the
disagreement at the top of this document visible at all.

### 12. A test set is a list of query ids, not a copy of the judgments

One query can belong to several sets. Store the judgment once, keyed by qid; let sets hold
**membership**. Copy the judgments per set instead, and revising a grade in one set leaves
the other stale — silently, with no error.

Here `q001` is in both `pooled_v1` and `stress_probe`; exporting both produces identical
qrels lines from a single stored judgment.

### 13. Refuse to export queries that would corrupt the set — and say why

Two guards, both catching failures that raise no error:

- **Incomplete queries are skipped.** `query_class` is derived from the *complete* relevant
  set, so a query abandoned at 4/15 with 1 relevant so far exports as `known_item` when it
  is really `topical` — a wrong label, silently.
- **Zero-relevant queries are skipped.** `gold_ids: []` is an entry no retriever can ever
  satisfy; it just quietly drags down every recall number it appears in.

Both are `--report`-visible and both have tests. The general principle: **an eval pipeline
should refuse to produce data it cannot stand behind, and name what it dropped.** Silent
truncation reads as "covered everything".

---

## Stage 5 — Measuring with it

### 14. One metrics implementation, imported everywhere

This repo grew **three** copies of nDCG (`scripts/eval.py`,
`scripts/query-understanding/qu_eval.py`, `scripts/rerank/rerank_eval.py`) and only one
learned graded gain. Adding a fourth in the UI's JavaScript would have guaranteed the
dashboard and the CLI eventually disagreed about the same test set — the worst possible
failure, because both look authoritative.

Now `src/hybrid_search/metrics.py` is the only implementation; the CLI and the web
endpoint both import it, and a test asserts `eval.py` defines no metric of its own. The
UI renders numbers it did not compute.

### 15. Binarize at evaluation time, not collection time

`gold_ids` = every document with **grade ≥ 1**, so MRR, Hits@1 and Recall are unchanged
from the binary era and remain comparable across old and new sets. The full grades live
alongside in `gold_grades` and only nDCG consumes them. TREC Deep Learning does the same
thing at a different threshold (rel ≥ 2 for MAP/MRR). One collection, several views.

---

## Adopt this in a week

1. **Day 1** — Write 20 queries by hand from real information needs. Do not look at
   results first. Do not generate them from documents.
2. **Day 1** — Decide your scale now. 0/1/2 is a good default. Decide the binarization
   threshold (gold = grade ≥ 1) and write it in a manifest.
3. **Day 2** — Build pooling: top-10 from each retriever, union, dedup, **drop rank and
   score**, deterministic shuffle seeded on the query.
4. **Day 2–3** — Build the thinnest judging UI you can that has: keyboard grading,
   judged items collapsing *in place*, free re-grading, and auto-save per click.
5. **Day 3–4** — Judge. Expect ~15 documents per query and roughly a day for 20 queries.
6. **Day 4** — Export topics + TREC qrels + a loadable deck. Add the two guards
   (incomplete, zero-relevant) before you trust an export.
7. **Day 5** — Wire `pytrec_eval` or your own single metrics module. Run your retrievers.
   Compare against whatever synthetic set you already had — **the disagreement is the
   most informative output of the whole week.**

---

## The three things most likely to go wrong

1. **Leaking rank into the judging UI.** The most common version is reusing your existing
   search-result component, which renders a position badge. Your judgments then encode
   your current ranking, and the benchmark can only agree with you. Enforce it at the API
   boundary, not in the renderer, and test it.

2. **Keying anything by query text.** It looks fine until the first typo fix or casing
   change orphans a query's judgments. Assign a stable id on first judgment and never
   renumber — every qrels file you have ever exported references it.

3. **Computing metrics more than once.** A dashboard that reimplements nDCG will drift
   from your CLI, and you will not notice until two numbers you trust contradict each
   other. One module, imported by everything, with a test asserting no second definition.

---

## Limits to state out loud when you present this

- **Five judged queries.** Enough to demonstrate the method, nowhere near enough to
  conclude vector beats hybrid. Say the number.
- **Depth-10, two-leg pools over a 92-document corpus** — roughly 16% of the corpus judged
  per query. Sound for comparing the three retrievers that built the pools; progressively
  less trustworthy for a future system that retrieves outside them.
- **Single assessor, no adjudication.** No inter-annotator agreement, so there is no
  measurement of how repeatable these judgments are. Cohen's κ over a second assessor is
  the obvious next step.
- **All five human-judged queries are topical**, so MRR and Hits@1 are `nan` on those sets.
  The comparison against the known-item-heavy synthetic set is therefore across different
  measures as well as different judgments — part of why they disagree.

*Citations above are from memory and should be verified before publication.*
