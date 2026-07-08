#!/usr/bin/env python3
"""In-process backend tests (no server/port): call the api route functions and
hybrid_search.core directly against a local Db2 connection. Exits non-zero on failure."""

import sys
import ibm_db
from hybrid_search import core as h
import build_fixtures as bf
import api

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def is_ranked(rows):
    """[(int chunk_id, float score), ...]"""
    return isinstance(rows, list) and all(
        isinstance(r, tuple) and len(r) == 2
        and isinstance(r[0], int) and isinstance(r[1], float) for r in rows)


def result_shape_ok(results):
    keys = {"rank", "chunk_id", "snippet", "text", "score", "score_type"}
    return all(keys <= set(r) for r in results)


def main():
    print("== hybrid_search.core: connection + retrieval legs ==")
    conn = h.connect()
    check("connect() opens a connection", conn is not None)

    lex = h.lexical(conn, "42615", 5)
    check("lexical('42615') returns ranked rows", is_ranked(lex) and len(lex) > 0, repr(lex[:2]))

    vec = h.vector(conn, "how do I turn text into vectors", 5)
    check("vector(semantic) returns ranked rows (APPROX index path)", is_ranked(vec) and len(vec) > 0, repr(vec[:2]))
    check("vector scores are cosine sims in [-1, 1]", all(-1.0 <= s <= 1.0 for _, s in vec), repr(vec[:2]))

    hyb = h.hybrid(conn, "how do I register an external model", 5)
    check("hybrid() returns ranked rows", is_ranked(hyb) and len(hyb) > 0, repr(hyb[:2]))

    expl = h.hybrid_explain(conn, "42615", 5)
    check("hybrid_explain() returns per-leg dicts",
          isinstance(expl, list) and len(expl) > 0
          and all({"chunk_id", "lex_norm", "vec_norm", "fused"} <= set(d) for d in expl))

    g = h.gates(conn, "42615")
    check("gates() returns bool flags for both legs",
          {"lexical_gated", "vector_gated"} <= set(g) and all(isinstance(v, bool) for v in g.values()), repr(g))

    snip = h.snippet(conn, lex[0][0])
    check("snippet() returns non-empty text", isinstance(snip, str) and len(snip) > 0)
    ibm_db.close(conn)

    print("== build_fixtures.responses_for: the payload the API serves ==")
    conn = h.connect()
    modes = bf.responses_for(conn, "42615", {27, 33, 36})
    ibm_db.close(conn)
    check("responses_for() has lexical/vector/hybrid", {"lexical", "vector", "hybrid"} <= set(modes))
    for m in ("lexical", "vector", "hybrid"):
        rs = modes.get(m, {}).get("results", [])
        check(f"responses_for[{m}] non-empty + well-shaped", len(rs) > 0 and result_shape_ok(rs))

    print("== api route functions (what /api/* return), called in-process ==")
    deck = api.queries()
    check("/api/queries returns a non-empty deck", isinstance(deck, list) and len(deck) > 0)

    res = api.search("42615")
    check("/api/search('42615') has query + 3 modes",
          res.get("query") == "42615" and {"lexical", "vector", "hybrid"} <= set(res))
    check("/api/search keyword: gold #36 in lexical top-3",
          any(r["chunk_id"] == 36 for r in res["lexical"]["results"][:3]),
          repr([r["chunk_id"] for r in res["lexical"]["results"]]))
    check("/api/search hybrid includes gate flags",
          isinstance(res["hybrid"].get("gates"), dict) and "vector_gated" in res["hybrid"]["gates"],
          repr(res["hybrid"].get("gates")))

    res2 = api.search("how do I turn text into vectors")
    check("/api/search semantic: vector leg non-empty", len(res2["vector"]["results"]) > 0)
    check("/api/search semantic: gold #14 in hybrid top-5",
          any(r["chunk_id"] == 14 for r in res2["hybrid"]["results"]),
          repr([r["chunk_id"] for r in res2["hybrid"]["results"]]))

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
