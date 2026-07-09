#!/usr/bin/env python3
"""Run every curated query through all three strategies ONCE and freeze the
results to fixtures.json, so the demo runs fully offline (no Db2/embedding server
at talk time). Reads/writes in this dir. Same response shape as the live API
(ui/api.py), so the frontend is identical for fixtures or --live."""

import json
import os
import ibm_db
from hybrid_search import core as h
from hybrid_search import understanding as qu   # extractive lexical cleaner (rare words)

K = 5  # results shown per strategy (and the "in top K?" cutoff)


def texts(conn, cid):
    full = h.snippet(conn, cid, 1000)
    return full[:100], full          # (one-line snippet, full text for click-to-expand)


def build_response(conn, query, lex_q, mode, gold, lex_pool, vec_pool, expl, g):
    # lexical/hybrid keyword leg searches the CLEANED query (rare words: filler and
    # common words like "book"/"looking for" dropped); vector leg keeps the raw
    # natural-language query for meaning.
    if mode == "lexical":
        ranked, score_type = h.lexical(conn, lex_q, K), "bm25"
    elif mode == "vector":
        ranked, score_type = h.vector(conn, query, K), "cosine"
    else:
        ranked, score_type = h.hybrid_split(conn, lex_q, query, K), "fused"

    results, gold_rank = [], None
    for rank, (cid, score) in enumerate(ranked, start=1):
        one, full = texts(conn, cid)
        is_gold = cid in gold
        if is_gold and gold_rank is None:
            gold_rank = rank
        r = {"rank": rank, "chunk_id": cid, "snippet": one, "text": full,
             "score": round(score, 4), "score_type": score_type, "is_gold": is_gold}
        if mode == "hybrid":
            # Provenance: which legs surfaced this chunk AND were not gated out.
            found_by = []
            if cid in lex_pool and not g["lexical_gated"]:
                found_by.append("bm25")
            if cid in vec_pool and not g["vector_gated"]:
                found_by.append("vector")
            lr, vr, ex = lex_pool.get(cid), vec_pool.get(cid), expl.get(cid, {})
            r["found_by"] = found_by
            r["per_leg"] = {
                "bm25":   {"rank": lr[0] if lr else None,
                           "score": round(lr[1], 4) if lr else None,
                           "norm": round(ex.get("lex_norm", 0.0), 4),
                           "gated": g["lexical_gated"]},
                "vector": {"rank": vr[0] if vr else None,
                           "score": round(vr[1], 4) if vr else None,
                           "norm": round(ex.get("vec_norm", 0.0), 4),
                           "gated": g["vector_gated"]},
            }
            r["contribution"] = {"bm25": round(h.W_LEX * ex.get("lex_norm", 0.0), 4),
                                 "vector": round(h.W_VEC * ex.get("vec_norm", 0.0), 4)}
        results.append(r)

    resp = {"query": query, "mode": mode, "k": K,
            "gold_chunk_ids": sorted(gold), "gold_rank": gold_rank, "results": results}
    if mode == "lexical":
        resp["lex_query"] = lex_q   # cleaned terms actually searched (for UI highlighting)
    if mode == "hybrid":
        resp["gates"] = g
    return resp


def responses_for(conn, query, gold):
    """All three strategy responses for one query. Shared by fixtures + live API.

    The keyword leg (lexical + hybrid's lexical half) searches an EXTRACTIVE cleaned
    query — filler phrases and common words ("book", "looking for", "a", "on") are
    stripped so it focuses on the rare, meaningful tokens. The vector leg embeds the
    raw natural-language query. This is the shipped smart_search(mode=off) behavior."""
    lex_q = qu.lexical_of(conn, query)
    lex_pool = {cid: (i + 1, s) for i, (cid, s) in enumerate(h.lexical(conn, lex_q, h.POOL))}
    vec_pool = {cid: (i + 1, s) for i, (cid, s) in enumerate(h.vector(conn, query, h.POOL))}
    expl = {e["chunk_id"]: e for e in h.hybrid_explain(conn, query, K, lexical_q=lex_q, semantic_q=query)}
    g = h.gates(conn, query, lexical_q=lex_q)
    return {m: build_response(conn, query, lex_q, m, gold, lex_pool, vec_pool, expl, g)
            for m in ("lexical", "vector", "hybrid")}


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "queries.json")) as f:
        deck = json.load(f)

    conn = h.connect()
    by_query = {}
    hits = {"lexical": 0, "vector": 0, "hybrid": 0}
    mrr = {"lexical": 0.0, "vector": 0.0, "hybrid": 0.0}

    for item in deck:
        modes = responses_for(conn, item["query"], set(item["gold_chunk_ids"]))
        by_query[str(item["id"])] = modes
        for m, resp in modes.items():
            if resp["gold_rank"] is not None:
                hits[m] += 1
                mrr[m] += 1.0 / resp["gold_rank"]

    ibm_db.close(conn)

    n = len(deck)
    out = {
        "meta": {"k": K, "pool": h.POOL,
                 "weights": {"lexical": h.W_LEX, "vector": h.W_VEC},
                 "vec_gate": h.VEC_GATE, "lex_gate": h.LEX_GATE, "count": n},
        "queries": deck,
        "by_query": by_query,
        "aggregate": {"n": n,
                      "hit_at_5": {m: f"{hits[m]}/{n}" for m in hits},
                      "hit_rate": {m: round(hits[m] / n, 3) for m in hits},
                      "mrr": {m: round(mrr[m] / n, 3) for m in mrr}},
    }
    with open(os.path.join(here, "fixtures.json"), "w") as f:
        json.dump(out, f, indent=2)

    # Acceptance check on the first deck query.
    a = by_query["1"]
    print(f"wrote fixtures.json — {n} queries x 3 modes")
    print(f"aggregate hit@5: {out['aggregate']['hit_at_5']}")
    print("ACCEPTANCE q1 ->",
          "lexical gold_rank:", a["lexical"]["gold_rank"],
          "| vector gold_rank:", a["vector"]["gold_rank"],
          "| hybrid gold_rank:", a["hybrid"]["gold_rank"],
          "| hybrid #1 found_by:", a["hybrid"]["results"][0].get("found_by"))


if __name__ == "__main__":
    main()
