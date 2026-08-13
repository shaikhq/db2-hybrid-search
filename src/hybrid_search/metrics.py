"""Retrieval metrics — the single implementation, shared by every caller.

Lifted out of scripts/eval.py so the CLI and the UI's Evaluate tab cannot drift apart.
Computing these twice is not hypothetical: this repo already grew three copies
(scripts/eval.py, scripts/query-understanding/qu_eval.py, scripts/rerank/rerank_eval.py)
and only one of them learned graded nDCG. A fourth, in JavaScript, would guarantee the
tab and the CLI eventually disagreed about the same test set.

`qu_eval.py` and `rerank_eval.py` still carry their own copies; migrating them is a
separate change, deliberately not half-done here.

All functions take `ranked` (a list of chunk ids, best first) and `gold` (a set of ids).
`ndcg_at_k` additionally accepts `grades` for graded relevance.
"""
import math

K = 5          # cutoff for Recall@K / nDCG@K (topical queries)
RETRIEVE = 10  # depth pulled from each leg — MRR sees ranks up to here


def rr(ranked, gold):
    """Reciprocal rank of the first gold document, or 0.0 if none is retrieved."""
    for i, cid in enumerate(ranked, start=1):
        if cid in gold:
            return 1.0 / i
    return 0.0


def hit1(ranked, gold):
    return 1.0 if ranked and ranked[0] in gold else 0.0


def recall_at_k(ranked, gold, k=K):
    return len(set(ranked[:k]) & gold) / len(gold) if gold else 0.0


def ndcg_at_k(ranked, gold, k=K, grades=None):
    """nDCG@k, graded when the item carries `gold_grades`.

    nDCG was defined on GRADED gain (Jarvelin & Kekalainen, TOIS 2002) — with binary
    judgments a perfect answer and a marginally on-topic one score identically, and the
    measure collapses into rank-weighted recall. Sets produced by the Label tab carry
    gold_grades ({chunk_id: 0|1|2}); the synthetic golden set does not.

    grades=None reproduces the binary behaviour exactly (gain 1.0 per gold doc), so the
    118-entry synthetic set's numbers are unchanged."""
    gain = (lambda cid: (2 ** grades[str(cid)] - 1) if str(cid) in grades else 0.0) \
        if grades else (lambda cid: 1.0 if cid in gold else 0.0)
    dcg = sum(gain(cid) / math.log2(i + 1) for i, cid in enumerate(ranked[:k], start=1))
    # The ideal ranking puts the highest gains first — with mixed grades, counting gold
    # documents is no longer the ideal DCG.
    best = sorted((gain(cid) for cid in (grades or gold)), reverse=True)[:k]
    ideal = sum(g / math.log2(i + 1) for i, g in enumerate(best, start=1))
    return dcg / ideal if ideal else 0.0


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def score_block(items, ranked_for, k=K):
    """Aggregate one slice of a test set into the four headline numbers per leg.

    `items` are golden-set-shaped dicts; `ranked_for(item)` returns that item's ranked
    chunk ids for the leg being scored. MRR and Hits@1 are known-item measures, Recall
    and nDCG topical ones — mean() yields nan for an empty slice, which is honest: it
    says "not measured here" rather than 0.0, which would read as "measured, and bad"."""
    ki = [it for it in items if it.get("query_class") == "known_item"]
    tp = [it for it in items if it.get("query_class") == "topical"]
    gold = lambda it: set(it["gold_ids"])
    return {
        "known_item": len(ki), "topical": len(tp),
        "mrr": mean(rr(ranked_for(it), gold(it)) for it in ki),
        "hits1": mean(hit1(ranked_for(it), gold(it)) for it in ki),
        "recall": mean(recall_at_k(ranked_for(it), gold(it), k) for it in tp),
        "ndcg": mean(ndcg_at_k(ranked_for(it), gold(it), k,
                               grades=it.get("gold_grades")) for it in tp),
    }
