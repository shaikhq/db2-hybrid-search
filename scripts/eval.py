#!/usr/bin/env python3
"""
eval.py — measure retrieval quality on a small GOLDEN EVAL SET.

The golden eval set below is a set of relevance judgments (a.k.a. *qrels* in
information-retrieval terms): each query is paired with its known-relevant
chunk(s). Reports MRR, Recall@K and Hits@1 for each leg (lexical, vector,
hybrid), plus a per-query table of where the first relevant result landed. Run it
after any change to chunking, the embedding model, the fusion gates, or the
weights, and judge the change by the numbers instead of by eyeballing one query.

    DB2_HOST=local python scripts/eval.py    # as the Db2 instance owner, local connection

The labels are loaded from the shared ui/queries.json so the eval and the demo
UI use the SAME curated set. They're for the IBM Db2 12.1.5 LLM-integration
reference doc; replace queries.json for your own corpus.
"""

import json
import os

import ibm_db
import hybrid_core as h

K = 5  # recall / top-k cutoff

# Golden eval set / relevance judgments (qrels): loaded from the shared
# ui/queries.json so the eval and the demo UI stay in sync. Each entry yields
# (query, {relevant chunk_id, ...}).
def _load_golden():
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "queries.json"),                 # staged alongside, if present
                 os.path.join(here, "..", "ui", "queries.json")):    # repo layout
        if os.path.exists(path):
            with open(path) as f:
                return [(item["query"], set(item["gold_chunk_ids"])) for item in json.load(f)]
    raise FileNotFoundError("queries.json not found (looked in script dir and ../ui/)")


GOLDEN = _load_golden()


def first_relevant_rank(ranked, relevant):
    for i, cid in enumerate(ranked, start=1):
        if cid in relevant:
            return i
    return None


def summarize(results):
    """results: [(ranked_ids, relevant_set)] -> (MRR, Recall@K, Hits@1)."""
    rr = recall = hit1 = 0.0
    for ranked, relevant in results:
        rank = first_relevant_rank(ranked, relevant)
        rr += 1.0 / rank if rank else 0.0
        recall += len(set(ranked[:K]) & relevant) / len(relevant)
        hit1 += 1.0 if ranked[:1] and ranked[0] in relevant else 0.0
    n = len(results) or 1
    return rr / n, recall / n, hit1 / n


def main():
    conn = h.connect()
    legs = {"lexical": h.lexical, "vector": h.vector, "hybrid": h.hybrid}
    collected = {name: [] for name in legs}
    per_query = []

    for query, relevant in GOLDEN:
        ranks = {}
        for name, fn in legs.items():
            ranked = [cid for cid, _ in fn(conn, query, 10)]
            collected[name].append((ranked, relevant))
            ranks[name] = first_relevant_rank(ranked, relevant)
        per_query.append((query, ranks))
    ibm_db.close(conn)

    def cell(r):
        return (str(r) if r else "-").rjust(3)

    print(f"\nGolden set: {len(GOLDEN)} queries — rank of first relevant result "
          f"(lower is better, '-' = not in top 10)\n")
    print(f"  {'query':52}  lex  vec  hyb")
    print(f"  {'-' * 52}  ---  ---  ---")
    for query, ranks in per_query:
        print(f"  {query[:52]:52}  {cell(ranks['lexical'])}  "
              f"{cell(ranks['vector'])}  {cell(ranks['hybrid'])}")

    print(f"\n  {'leg':8}  {'MRR':>6}  {('Recall@' + str(K)):>9}  {'Hits@1':>7}")
    print(f"  {'-' * 8}  {'-' * 6}  {'-' * 9}  {'-' * 7}")
    for name in legs:
        mrr, recall, hit1 = summarize(collected[name])
        print(f"  {name:8}  {mrr:6.3f}  {recall:9.3f}  {hit1:7.3f}")
    print()


if __name__ == "__main__":
    main()
