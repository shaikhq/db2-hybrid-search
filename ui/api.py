#!/usr/bin/env python3
"""Live backend for the demo (`./ui/run.sh --live`) — a thin wrapper over the
search engine returning the SAME JSON shape as fixtures.json, so the frontend is
identical offline or live. The default demo is offline (static page + fixtures);
this exists for ad-hoc queries during Q&A."""

import hashlib
import json
import math
import logging
import os
import random
import re
import shutil
import tempfile
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
import ibm_db

from hybrid_search import core as h
from hybrid_search import understanding as qu   # adaptive query-understanding layer
from hybrid_search import rerank as rr          # optional post-fusion cross-encoder stage
from hybrid_search import metrics as mx         # the ONE metrics implementation
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

# Graded relevance, 3-point. Modern IR judges on a scale rather than a binary: nDCG is
# built on graded gain, so binary judgments make a perfect answer and a marginally
# on-topic one score identically. Three levels rather than TREC Deep Learning's four —
# a solo assessor over ~300 judgments stays far more self-consistent, and this domain has
# no equivalent of DL's "answers but buried in extraneous information" distinction.
# gold_ids binarizes at grade >= 1, so hit-rate / MRR / Recall are unaffected.
GRADES = {"irrelevant": 0, "relevant": 1, "highly_relevant": 2}
SCALE = "graded3"
LABELS = set(GRADES) | {"skip"}  # skip is not a grade: it is a gap, never a 0
POOL_K = 10                      # top-k taken from EACH leg before the union


def _set_name():
    """The default test set. A collection is (corpus, topics, qrels); one corpus supports
    many named sets, and the exporter emits one topics + one qrels file per set. The Label
    tab picks a set per request; this is only the fallback when it doesn't."""
    return os.environ.get("JUDGMENTS_SET") or "pooled_v1"


def _new_set():
    """A set owns membership and provenance — never judgments. `members` (not `queries`)
    is also what distinguishes a v3 set from a v2 one during migration detection."""
    return {"assessor": os.environ.get("JUDGMENTS_ASSESSOR", ""),
            "pool_depth": POOL_K, "legs": ["lexical", "vector"],
            "scale": SCALE, "members": []}


def _norm(text):
    """Identity key for a query: case- and whitespace-insensitive. Retyping "Managing
    Stress" must resolve to the qid already holding its judgments rather than silently
    opening a second, empty entry. The text is still STORED exactly as typed."""
    return " ".join(str(text or "").split()).casefold()


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
        return {"queries": {}, "sets": {}}
    if "sets" not in data and "queries" in data:
        data = _migrate_v1(data)
    if any("queries" in s for s in (data.get("sets") or {}).values()):
        data = _migrate_v2(data)
    data.setdefault("queries", {})
    data.setdefault("sets", {})
    return data


def _migrate_v1(old):
    """Convert the first-generation store — {"queries": {<query text>: {...}}} — into
    named sets with stable qids.

    Query text was the key there, so retyping a query with different casing stranded its
    judgments on the old spelling. qids fix that. Ordered by text so the mapping is
    reproducible if this ever has to be re-run. _write_judgments() backs the old file up
    before the first write in the new shape."""
    queries = {}
    for i, (text, entry) in enumerate(sorted((old.get("queries") or {}).items()), start=1):
        queries[f"q{i:03d}"] = {"text": text,
                                "pool_size": entry.get("pool_size", 0),
                                "labels": dict(entry.get("labels") or {})}
    # Emits the v2 shape; _load_judgments() then runs _migrate_v2 over it, so the two
    # conversions compose instead of each needing to know about the other.
    set_ = _new_set()
    set_.pop("members", None)
    set_["queries"] = queries
    return {"sets": {_set_name(): set_}}


def _migrate_v2(old):
    """Convert set-owned judgments into the membership model.

    v2 nested each query INSIDE a set, so filing one query into two sets meant copying
    its judgments — and revising one copy left the other stale. A relevance judgment is a
    fact about (query, document), independent of which collection you file it in; a test
    set is a named LIST of query ids that references those facts. Same separation TREC and
    BEIR make between topics and collections.

    Two sets holding the same query text collapse to one qid with membership in both —
    which is the whole point, and is lossless as long as their labels agree. When they
    disagree, the later set's labels win per (qid, cid) and the loss is reported in the
    server log rather than passed off as a clean conversion."""
    queries, by_text, sets = {}, {}, {}
    for name, set_ in sorted((old.get("sets") or {}).items()):
        members = []
        for qid, entry in sorted((set_.get("queries") or {}).items()):
            key = _norm(entry.get("text"))
            if key in by_text:
                target = by_text[key]
                clashes = {c for c, v in (entry.get("labels") or {}).items()
                           if c in queries[target]["labels"]
                           and queries[target]["labels"][c] != v}
                if clashes:
                    logging.getLogger("uvicorn.error").warning(
                        "judgments migration: %r appears in more than one set with "
                        "conflicting labels for chunk(s) %s — keeping %r's.",
                        entry.get("text"), sorted(clashes), name)
                queries[target]["labels"].update(entry.get("labels") or {})
                queries[target]["pool_size"] = max(queries[target]["pool_size"],
                                                   entry.get("pool_size", 0))
            else:
                target = f"q{len(queries) + 1:03d}"
                by_text[key] = target
                queries[target] = {"text": entry.get("text", ""),
                                   "pool_size": entry.get("pool_size", 0),
                                   "labels": dict(entry.get("labels") or {})}
            if target not in members:
                members.append(target)
        meta = {k: v for k, v in set_.items() if k != "queries"}
        sets[name] = {**meta, "members": members}
    return {"queries": queries, "sets": sets}


def _active_set(data, name=None):
    """Get-or-create a set. Sets own membership and provenance only — never judgments."""
    set_ = data.setdefault("sets", {}).setdefault(name or _set_name(), _new_set())
    set_.setdefault("members", [])
    return set_


def _qid_for(data, text):
    """The existing qid for this query text, or the next free one.

    Store-scoped, not set-scoped: qids are the join key every set's members list and every
    exported qrels file references, so they must be unique across the whole store. Stable
    and immutable once assigned — renumbering would silently invalidate exported qrels."""
    key = _norm(text)
    for qid, entry in data["queries"].items():
        if _norm(entry.get("text")) == key:
            return qid
    # max()+1, never len()+1 — a deleted query would otherwise cause a collision.
    nums = [int(q[1:]) for q in data["queries"] if q[1:].isdigit()]
    return f"q{max(nums, default=0) + 1:03d}"


def _summarize(entry):
    labels = entry.get("labels") or {}
    counts = {name: sum(1 for v in labels.values() if v == name) for name in sorted(LABELS)}
    gold = sum(n for name, n in counts.items() if GRADES.get(name, -1) >= 1)
    return {"text": entry.get("text", ""), "pool_size": entry.get("pool_size", 0),
            "decided": len(labels), "gold": gold, "counts": counts,
            "complete": bool(entry.get("pool_size")) and len(labels) >= entry["pool_size"]}


def _write_judgments(data):
    """Write the whole store atomically: temp file in the same directory, fsync, then
    os.replace. A crash mid-write leaves the previous store intact rather than a
    truncated JSON file that would fail to parse on the next launch."""
    path = _judgments_path()
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    # One-time safety net: the first write after a v1 -> sets migration keeps a copy of
    # the pre-migration file. Judgments are hand-produced and unrecoverable if a schema
    # change goes wrong. (*.bak is already gitignored.)
    if not os.path.exists(path + ".bak"):
        try:
            with open(path) as f:
                on_disk = json.load(f)
            stale = ("sets" not in on_disk                                  # v1
                     or any("queries" in s for s in on_disk["sets"].values()))  # v2
            if stale:
                shutil.copy2(path, path + ".bak")
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            pass
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
         k: int = Query(POOL_K, description="top-k taken from EACH leg before the union")):
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
    """Every judged query — the frontend merges these into a freshly built pool so a
    re-typed query resumes with its existing labels already applied.

    Judgments are store-wide, not per set: a query judged once is judged for every set it
    belongs to. `by_text` is a normalized-text index onto the same entries, because the UI
    knows the string the user typed, not its qid.

    `sets` maps each set name to its members, so the UI can show which sets a query is
    already filed in without a second round trip."""
    data = _load_judgments()
    by_text = {_norm(e.get("text")): {"qid": qid, "pool_size": e.get("pool_size", 0),
                                      "labels": e.get("labels", {})}
               for qid, e in data["queries"].items()}
    return {"set": _set_name(), "scale": SCALE, "queries": data["queries"],
            "sets": {n: list(s.get("members") or []) for n, s in data["sets"].items()},
            "by_text": by_text}


@app.get("/api/sets")
def get_sets():
    """Every test set with its provenance and a per-member summary — the one response the
    Label tab's sidebar renders. This is what "browse a test set" means: its topics, how
    far each is judged, and how many gold documents each yielded."""
    data = _load_judgments()
    out = {}
    for name, set_ in sorted(data["sets"].items()):
        members = [q for q in (set_.get("members") or []) if q in data["queries"]]
        summaries = {qid: _summarize(data["queries"][qid]) for qid in members}
        out[name] = {**{k: v for k, v in set_.items() if k != "members"},
                     "members": members, "queries": summaries,
                     "complete": sum(1 for s in summaries.values() if s["complete"]),
                     "judgments": sum(s["decided"] for s in summaries.values())}
    return {"active": _set_name(), "scale": SCALE, "sets": out}


@app.post("/api/sets")
def create_set(payload: dict = Body(...)):
    """Create an empty test set. Names are the identity of an assessment effort and end up
    in exported filenames, so they are restricted to path-safe characters."""
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise HTTPException(status_code=400,
                            detail="name may contain only letters, digits, . _ and -")
    data = _load_judgments()
    if name in data["sets"]:
        raise HTTPException(status_code=400, detail=f"set {name!r} already exists")
    _active_set(data, name)
    _write_judgments(data)
    return {"ok": True, "name": name}


@app.post("/api/sets/{name}/members")
def add_member(name: str, payload: dict = Body(...)):
    """File an already-judged query into another set. Idempotent.

    Nothing is copied: the set gains a reference to the qid, and both sets read the same
    judgments. Correcting a grade later fixes it in every set at once."""
    qid = (payload.get("qid") or "").strip()
    data = _load_judgments()
    if name not in data["sets"]:
        raise HTTPException(status_code=404, detail=f"no such set {name!r}")
    if qid not in data["queries"]:
        raise HTTPException(status_code=404, detail=f"no such query {qid!r}")
    set_ = _active_set(data, name)
    if qid not in set_["members"]:
        set_["members"].append(qid)
        _write_judgments(data)
    return {"ok": True, "set": name, "qid": qid, "members": set_["members"]}


@app.delete("/api/sets/{name}/members/{qid}")
def remove_member(name: str, qid: str):
    """Unfile a query from a set. Removes MEMBERSHIP ONLY — the judgments belong to the
    query, not the set, and are still there for every other set that references them."""
    data = _load_judgments()
    if name not in data["sets"]:
        raise HTTPException(status_code=404, detail=f"no such set {name!r}")
    set_ = _active_set(data, name)
    if qid in set_["members"]:
        set_["members"].remove(qid)
        _write_judgments(data)
    return {"ok": True, "set": name, "qid": qid, "members": set_["members"]}


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
    set_name = (payload.get("set") or "").strip() or _set_name()
    set_ = _active_set(data, set_name)
    qid = _qid_for(data, query)
    entry = data["queries"].setdefault(
        qid, {"text": query, "pool_size": pool_size, "labels": {}})
    entry["pool_size"] = pool_size
    entry["labels"][str(cid)] = label
    # Judging a query into a set files it there; membership is the only per-set state.
    if qid not in set_["members"]:
        set_["members"].append(qid)
    _write_judgments(data)
    labels = entry["labels"]
    counts = {name: sum(1 for v in labels.values() if v == name)
              for name in sorted(LABELS)}
    return {"ok": True, "set": set_name, "scale": SCALE, "qid": qid,
            "query": entry["text"], "cid": cid, "label": label, "pool_size": pool_size,
            "decided": len(labels), "skipped": counts["skip"], "counts": counts}


# ------------------------------------------------------------- Evaluate tab
# Run a named test set through all three Db2 legs and score it. The metrics come from
# hybrid_search.metrics — the SAME functions scripts/eval.py uses — so this tab and the
# CLI can never report different numbers for the same set. The reranker is deliberately
# not a fourth leg: it consumes hybrid's output rather than competing with it, and it
# runs outside Db2 (see scripts/rerank/rerank_eval.py).

EVAL_LEGS = {"lexical": h.lexical, "vector": h.vector, "hybrid": h.hybrid}


def _eval_sets_dir():
    """Where the exported test-set decks live. Same trap as JUDGMENTS_PATH: `--live` runs
    from a wiped stage that does not carry data/eval/, so run.sh exports this at the real
    repo. Resolved per call so tests can redirect it."""
    return os.environ.get("EVAL_SETS_DIR") or os.path.join(
        os.path.dirname(HERE), "data", "eval", "sets")


def _eval_decks():
    """{name: path} for every deck that can be evaluated — the exported labeled sets plus
    the synthetic golden set. Being able to switch between them is the whole point of
    keeping human-judged and generated judgments in separate files."""
    decks = {}
    directory = _eval_sets_dir()
    if os.path.isdir(directory):
        for fn in sorted(os.listdir(directory)):
            if fn.endswith(".json") and fn != "manifest.json":
                decks[fn[:-5]] = os.path.join(directory, fn)
    try:
        from hybrid_search import evalset
        decks.setdefault("golden_set", evalset.resolve())
    except Exception:
        pass
    return decks


def _load_deck(path):
    items = json.load(open(path, encoding="utf-8"))
    items = items["queries"] if isinstance(items, dict) else items
    for it in items:
        it["gold_ids"] = [int(g) for g in it.get("gold_ids", [])]
        it.setdefault("split", "train")
        it.setdefault("query_class", "known_item" if len(it["gold_ids"]) == 1 else "topical")
    return items


def _finite(v):
    """Strict JSON has no nan. mean() yields nan for an empty slice — MRR over zero
    known-item queries, say — and that means "not measured here", so it is sent as null.
    Coercing it to 0.0 would read as "measured, and the worst possible score"."""
    return None if isinstance(v, float) and not math.isfinite(v) else v


@app.get("/api/eval_sets")
def eval_sets():
    """The decks available to evaluate, with enough provenance to tell them apart."""
    out = {}
    for name, path in _eval_decks().items():
        try:
            items = _load_deck(path)
        except (OSError, json.JSONDecodeError, KeyError):
            continue
        sources = sorted({it.get("source", "?") for it in items})
        out[name] = {"queries": len(items), "sources": sources,
                     "graded": any(it.get("gold_grades") for it in items),
                     "known_item": sum(1 for it in items if it["query_class"] == "known_item"),
                     "topical": sum(1 for it in items if it["query_class"] == "topical")}
    return {"sets": out}


@app.get("/api/evaluate")
def evaluate(name: str = Query(..., alias="set",
                               description="name of the test set to evaluate")):
    """Score one test set across all three legs.

    Returns the same blocks scripts/eval.py prints (heldout / train / all) plus per-query
    rows, because an aggregate alone hides WHICH queries are failing."""
    decks = _eval_decks()
    if name not in decks:
        raise HTTPException(status_code=404,
                            detail=f"no such test set {name!r} — have: {sorted(decks)}")
    items = _load_deck(decks[name])

    conn = h.connect()
    try:
        ranked = {(leg, it["id"]): [int(cid) for cid, _ in fn(conn, it["query"], mx.RETRIEVE)]
                  for it in items for leg, fn in EVAL_LEGS.items()}
        meta = {cid: h.book_meta(conn, cid)
                for cid in {c for ids in ranked.values() for c in ids[:mx.K]}}
    finally:
        ibm_db.close(conn)

    blocks = {}
    for title, keep in (("heldout", lambda it: it["split"] == "holdout"),
                        ("train", lambda it: it["split"] == "train"),
                        ("all", lambda it: True)):
        rows = [it for it in items if keep(it)]
        blocks[title] = {
            leg: {k: _finite(v) for k, v in
                  mx.score_block(rows, lambda it, l=leg: ranked[(l, it["id"])]).items()}
            for leg in EVAL_LEGS}

    per_query = []
    for it in items:
        grades = it.get("gold_grades") or {}
        gold = set(it["gold_ids"])
        per_query.append({
            "id": it["id"], "query": it["query"], "query_class": it["query_class"],
            "split": it["split"], "gold_ids": it["gold_ids"], "gold_grades": grades,
            "legs": {leg: [{"chunk_id": cid, "gold": cid in gold,
                            "grade": grades.get(str(cid)),
                            **meta.get(cid, {})} for cid in ranked[(leg, it["id"])][:mx.K]]
                     for leg in EVAL_LEGS},
        })
    return {"set": name, "queries": len(items), "k": mx.K, "retrieve": mx.RETRIEVE,
            "legs": list(EVAL_LEGS), "blocks": blocks, "per_query": per_query}


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
