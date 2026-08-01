#!/usr/bin/env python3
"""Live backend for the demo (`./ui/run.sh --live`) — a thin wrapper over the
search engine returning the SAME JSON shape as fixtures.json, so the frontend is
identical offline or live. The default demo is offline (static page + fixtures);
this exists for ad-hoc queries during Q&A."""

import hashlib
import json
import logging
import os
import random
import tempfile
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
import ibm_db

from hybrid_search import core as h
from hybrid_search import understanding as qu   # adaptive query-understanding layer
from hybrid_search import rerank as rr          # optional post-fusion cross-encoder stage
import build_fixtures as bf   # responses_for()
import demo_view as dv         # outcome-translation (verdicts + book labels)

# Log hybrid_search.core's SQL to the uvicorn console (reuse uvicorn's handler; fall
# back to a basic one if run standalone).
_uvicorn_handlers = logging.getLogger("uvicorn").handlers
if _uvicorn_handlers:
    h.log.handlers = _uvicorn_handlers
    h.log.propagate = False
else:
    logging.basicConfig(level=logging.INFO)
    h.log.propagate = True
h.log.setLevel(logging.INFO)

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "queries.json")) as f:
    DECK = json.load(f)
GOLD = {item["query"]: set(item["gold_chunk_ids"]) for item in DECK}

# Demo view (additive): its own deck + a book-id -> title/author lookup.
with open(os.path.join(HERE, "demo_queries.json")) as f:
    DEMO_DECK = json.load(f)
DEMO_GOLD = {d["query"]: set(d["gold_chunk_ids"]) for d in DEMO_DECK}
DEMO_ITEM = {d["query"]: d for d in DEMO_DECK}
# corpus.csv sits at <repo>/data/ when run from the repo, but --live runs from a
# staged copy (/tmp/hybrid-ui-<port>) where run.sh drops it at <stage>/data/. Try both,
# and say so when neither hits: without it label_for() silently falls back to parsing
# "Title by Author." off the chunk text, which is easy to mistake for working.
_CORPUS = next(
    (p for p in (os.path.join(HERE, "data", "corpus.csv"),
                 os.path.join(os.path.dirname(HERE), "data", "corpus.csv"))
     if os.path.exists(p)), None)
if _CORPUS:
    BOOK_LOOKUP = dv.load_book_lookup(_CORPUS)
else:
    BOOK_LOOKUP = {}
    logging.getLogger("uvicorn.error").warning(
        "corpus.csv not found under %s — book titles fall back to text parsing.", HERE)

app = FastAPI(title="Db2 Hybrid Search Demo", docs_url="/docs")


@app.get("/api/queries")
def queries():
    """The curated demo deck (query, type, gold chunk IDs, note)."""
    return DECK


@app.get("/api/search")
def search(q: str = Query(..., description="search text"), k: int = bf.K,
           rerank: Optional[bool] = Query(None, description="override the post-fusion reranker")):
    """All three strategy responses for a query (lexical, vector, hybrid).
    gold_chunk_ids come from the curated set when the query matches one.
    The Search tab's hybrid results pass through the post-fusion reranker when
    requested via `rerank` (the tab's toggle); absent that, the RERANK_ON env
    default applies. The Demo tab never reranks."""
    do_rerank = rr.RERANK_ON if rerank is None else bool(rerank)
    gold = GOLD.get(q, set())
    conn = h.connect()
    try:
        modes = bf.responses_for(conn, q, gold, rerank=do_rerank)
    finally:
        ibm_db.close(conn)
    # If reranking was requested but the reranker was unreachable, say so explicitly
    # rather than pass off fusion order as "reranked" — the UI shows an error.
    fell_back = do_rerank and modes.get("hybrid", {}).get("rerank_fell_back", False)
    out = {"query": q, "gold_chunk_ids": sorted(gold),
           "reranked": do_rerank and not fell_back, **modes}
    if fell_back:
        out["rerank_unavailable"] = True
    return out


@app.get("/api/smart_search")
def smart_search(q: str = Query(..., description="search text"), k: int = bf.K):
    """The shipped canonical path: extractive lexical cleaning always on, generative
    expansion gated by QU_MODE (default 'off'). Returns the ranked results plus the
    understanding metadata (route, whether the LLM fired, the two leg queries)."""
    conn = h.connect()
    try:
        ranked, meta = qu.smart_search(conn, q, k)
        results = [{"chunk_id": cid, "score": score,
                    "snippet": h.snippet(conn, cid)} for cid, score in ranked]
    finally:
        ibm_db.close(conn)
    return {"query": q, "mode": qu.MODE, "understanding": meta, "results": results}


@app.get("/api/demo_deck")
def demo_deck():
    """The curated demo deck (query, type, gold ids, scenario)."""
    return DEMO_DECK


@app.get("/api/demo")
def demo(q: str = Query(..., description="search text")):
    """Demo view model for a query: each strategy translated to a verdict
    (found / wrong / nothing) with the shown book's title + author."""
    gold = DEMO_GOLD.get(q, set())
    item = DEMO_ITEM.get(q, {"id": 0, "query": q, "query_type": None,
                             "query_class": "known_item", "scenario": "",
                             "gold_chunk_ids": sorted(gold)})
    conn = h.connect()
    try:
        responses = bf.responses_for(conn, q, gold)
    finally:
        ibm_db.close(conn)
    return dv.view_model(responses, item, BOOK_LOOKUP, k=bf.K)


# ---------------------------------------------------------------- Label tab
# Pooled relevance labeling (TREC-style): union both legs' top-k, discard rank,
# judge each unique document against the query. Spec + the approved interaction
# contract live in docs/label-tab-plan.md.

LABELS = {"relevant", "irrelevant", "skip"}


def _judgments_path():
    """Where judgments live — resolved per call, never cached at import.

    The default is only correct when api.py runs from the repo. `--live` runs it from
    a per-launch-wiped stage (/tmp/hybrid-ui-$PORT), where this default would point at
    /tmp and lose every label on the next launch — so run.sh's --live branch exports
    JUDGMENTS_PATH at the real repo. Resolving lazily is also what lets tests redirect
    the store without reimporting the module."""
    return os.environ.get("JUDGMENTS_PATH") or os.path.join(
        os.path.dirname(HERE), "data", "eval", "judgments.json")


def build_pool(query, lex, vec):
    """Union the two legs, dedup by chunk id, DISCARD RANK, shuffle deterministically.

    Rank and which leg surfaced a document never leave this function: showing either
    anchors the assessor, which is the whole point of pooling. The shuffle is seeded on
    the query so a resumed session sees the same order every time — judgments are keyed
    by chunk id and survive regardless, but a list that reshuffles makes "next unlabeled
    card" jump around and re-reading already-judged cards wastes the assessor's attention.
    """
    cids = sorted({int(cid) for cid, _ in lex} | {int(cid) for cid, _ in vec})
    seed = int(hashlib.md5(query.encode("utf-8")).hexdigest()[:16], 16)
    random.Random(seed).shuffle(cids)
    return cids


def _load_judgments():
    """The store, or an empty one if it doesn't exist yet. A corrupt store raises
    rather than resetting to empty — silently discarding hours of labeling is far
    worse than a 500 that says so."""
    try:
        with open(_judgments_path()) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"queries": {}}
    data.setdefault("queries", {})
    return data


def _write_judgments(data):
    """Write the whole store atomically: temp file in the same directory, fsync, then
    os.replace. A crash mid-write leaves the previous store intact rather than a
    truncated JSON file that would fail to parse on the next launch."""
    path = _judgments_path()
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".judgments-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@app.get("/api/pool")
def pool(q: str = Query(..., description="query to build a labeling pool for"),
         k: int = Query(10, description="top-k taken from EACH leg before the union")):
    """The unranked, deduped labeling pool for a query.

    `legs` reports how many results each retriever returned *in aggregate* — enough for
    the UI to say "pool built from 1 of 2 retrievers" when one leg comes back empty,
    without revealing which leg surfaced any individual document."""
    conn = h.connect()
    try:
        lex = h.lexical(conn, q, k)
        vec = h.vector(conn, q, k)
        docs = [{"chunk_id": cid, "snippet": h.snippet(conn, cid),
                 **h.book_meta(conn, cid)} for cid in build_pool(q, lex, vec)]
    finally:
        ibm_db.close(conn)
    return {"query": q, "pool_size": len(docs),
            "legs": {"lexical": len(lex), "vector": len(vec)}, "pool": docs}


@app.get("/api/judgments")
def judgments():
    """The whole judgments store — the frontend merges it into a freshly built pool so
    a re-typed query resumes with its existing labels already applied."""
    return _load_judgments()


@app.post("/api/judgments")
def post_judgment(payload: dict = Body(...)):
    """Record one {query, cid, label, pool_size} judgment.

    Idempotent per (query, cid): re-labeling overwrites in place, which is what makes
    the UI's free relabeling free. Read-merge-write is safe here because the app is
    single-user loopback; it would need locking if that ever changed."""
    query = (payload.get("query") or "").strip()
    label = payload.get("label")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    if label not in LABELS:
        raise HTTPException(status_code=400,
                            detail=f"label must be one of {sorted(LABELS)}")
    try:
        cid = int(payload.get("cid"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="cid must be an integer chunk id")
    try:
        pool_size = int(payload.get("pool_size"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="pool_size is required (the exporter's completeness "
                                   "guard cannot reconstruct it later)")
    if pool_size <= 0:
        # A query whose pool came back empty has nothing to judge; recording it would
        # later export as gold_ids: [] — an eval entry no retriever can ever satisfy.
        raise HTTPException(status_code=400,
                            detail="pool_size must be > 0 — an empty pool records nothing")

    data = _load_judgments()
    entry = data["queries"].setdefault(query, {"pool_size": pool_size, "labels": {}})
    entry["pool_size"] = pool_size
    entry["labels"][str(cid)] = label
    _write_judgments(data)
    labels = entry["labels"]
    return {"ok": True, "query": query, "cid": cid, "label": label,
            "pool_size": pool_size, "decided": len(labels),
            "skipped": sum(1 for v in labels.values() if v == "skip")}


class NoCacheHTML(StaticFiles):
    """StaticFiles, but HTML always revalidates. index.html carries the ?v= busters
    for the JS/CSS and nothing busts index.html itself, so a browser holding a stale
    copy pairs old markup with new scripts — startBoot() then finds no #start-canvas
    and returns silently, leaving a blank page and no console error. "no-cache" still
    permits a 304 via the ETag, so the revalidation is cheap."""

    def file_response(self, full_path, *args, **kwargs):
        resp = super().file_response(full_path, *args, **kwargs)
        if str(full_path).endswith(".html"):
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


# Serve the same static UI; API routes above take precedence over this mount.
app.mount("/", NoCacheHTML(directory=os.path.join(HERE, "static"), html=True), name="static")
