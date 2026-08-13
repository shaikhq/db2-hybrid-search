#!/usr/bin/env python3
"""export_judgments.py — turn pooled relevance judgments into a test collection.

Reads the Label tab's store (data/eval/judgments.json) and emits, for one named set:

  data/eval/topics/<set>.tsv     qid <TAB> query text
  data/eval/qrels/<set>.qrels    qid 0 chunk_id relevance   (TREC qrels format)
  data/eval/sets/<set>.json      golden-set-shaped, directly loadable by scripts/eval.py
  data/eval/sets/manifest.json   provenance for every set (assessor, pool depth, legs)

Topics and qrels are the standard IR split: a test collection is (corpus, topics,
qrels), the three joined by a stable qid. Keeping them in separate files is what lets
one corpus carry several independent test sets, and the TREC qrels format is what makes
trec_eval / pytrec_eval / ir_measures work on this data without an adapter.

IT DOES NOT TOUCH data/eval/golden_set.json. Human-judged and synthetically generated
judgments are separate assessment efforts, and mixing them into one file destroys the
ability to report either alone — "hit-rate over 20 human-verified queries" is a
different, far stronger claim than "hit-rate over 118 mostly-unreviewed silver ones".
Standard practice is one qrels file per effort, composed at LOAD time, not storage time:

    PYTHONPATH=src DB2_HOST=local python scripts/eval.py data/eval/sets/pooled_v1.json
    PYTHONPATH=src DB2_HOST=local python scripts/eval.py          # the silver deck

(`scripts/eval.py` already accepts a path or $GOLDEN_SET via hybrid_search.evalset.)
--merge-golden exists for the rare case where you deliberately want them combined.

Relevance is binary: relevant -> 1, irrelevant -> 0. Skips are OMITTED — "skip" means
"seen, no judgment", which is a gap in the qrels, not a judgment of non-relevance.

Run:
    PYTHONPATH=src python scripts/export_judgments.py --report      # dry run, writes nothing
    DB2_HOST=local PYTHONPATH=src python scripts/export_judgments.py

Two queries are skipped by default, because exporting them corrupts the eval set in ways
nothing downstream would flag:
  - INCOMPLETE (decided < pool_size): query_class is derived from the complete relevant
    set, so a query abandoned at 4/15 with 1 relevant exports as known_item when it is
    really topical. --include-partial overrides.
  - ZERO RELEVANT: gold_ids: [] is an entry no retriever can ever satisfy; it silently
    drags down every recall number it appears in.
"""
import argparse
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

DEFAULT_STORE = os.path.join(REPO, "data", "eval", "judgments.json")
DEFAULT_GOLDEN = os.path.join(REPO, "data", "eval", "golden_set.json")
TOPICS_DIR = os.path.join(REPO, "data", "eval", "topics")
QRELS_DIR = os.path.join(REPO, "data", "eval", "qrels")
SETS_DIR = os.path.join(REPO, "data", "eval", "sets")

# Graded relevance, 3-point. MUST match ui/api.py's GRADES — the store holds the level
# names, the qrels file holds the numbers. "skip" is deliberately absent: see the docstring.
REL = {"irrelevant": 0, "relevant": 1, "highly_relevant": 2}
SCALE = "graded3"
GOLD_THRESHOLD = 1     # gold_ids = grade >= 1, so MRR/Hits@1/Recall stay comparable
                       # with the binary sets. nDCG uses the full grades via gold_grades.


def norm(text):
    """Identity key for a query. MUST match ui/api.py's _norm(): the golden-set merge
    uses it to decide whether a labeled query is the same one as an existing entry."""
    return " ".join(str(text or "").split()).casefold()


def atomic_write(path, render):
    """Write via temp file + os.replace, like the judgments store. golden_set.json is
    118 hand-curated entries; a crash mid-write must not truncate it."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".export-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            render(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_store(store_path):
    """Normalize any store generation to v3: {"queries": {qid: entry}, "sets": {...}}.

    v1 keyed queries by text; v2 nested them inside each set; v3 stores each judgment once
    and lets sets reference it by qid. Old backups still export without being migrated."""
    with open(store_path, encoding="utf-8") as f:
        data = json.load(f)
    if "sets" not in data:                                            # v1
        queries = {f"q{i:03d}": {"text": t, "pool_size": e.get("pool_size", 0),
                                 "labels": e.get("labels") or {}}
                   for i, (t, e) in enumerate(sorted((data.get("queries") or {}).items()), 1)}
        return {"queries": queries, "sets": {"pooled_v1": {"members": list(queries)}}}
    if any("queries" in s for s in data["sets"].values()):            # v2
        queries, by_text, sets = {}, {}, {}
        for name, set_ in sorted(data["sets"].items()):
            members = []
            for _, entry in sorted((set_.get("queries") or {}).items()):
                key = norm(entry.get("text"))
                if key not in by_text:
                    by_text[key] = f"q{len(queries) + 1:03d}"
                    queries[by_text[key]] = {"text": entry.get("text", ""),
                                             "pool_size": entry.get("pool_size", 0),
                                             "labels": dict(entry.get("labels") or {})}
                else:
                    queries[by_text[key]]["labels"].update(entry.get("labels") or {})
                if by_text[key] not in members:
                    members.append(by_text[key])
            sets[name] = {**{k: v for k, v in set_.items() if k != "queries"},
                          "members": members}
        return {"queries": queries, "sets": sets}
    return data


def load_set(store_path, set_name):
    """(provenance, {qid: entry}) for one named set, resolved through its members."""
    data = load_store(store_path)
    if set_name not in data["sets"]:
        raise SystemExit(f"no such set {set_name!r} — have: {sorted(data['sets'])}")
    set_ = data["sets"][set_name]
    meta = {k: v for k, v in set_.items() if k != "members"}
    # Judgments live once, in data["queries"]; the set only references them. A query
    # filed into several sets exports into all of them from that single stored judgment.
    return meta, {qid: data["queries"][qid]
                  for qid in (set_.get("members") or []) if qid in data["queries"]}


def load_queries(store_path, set_name):
    return load_set(store_path, set_name)[1]


def summarize(entry):
    labels = entry.get("labels") or {}
    return {
        "text": entry.get("text", ""),
        "pool_size": int(entry.get("pool_size", 0)),
        "decided": len(labels),
        "skipped": sum(1 for v in labels.values() if v == "skip"),
        "relevant": sorted(int(c) for c, v in labels.items()
                           if REL.get(v, -1) >= GOLD_THRESHOLD),
        "grades": {c: REL[v] for c, v in labels.items()
                   if REL.get(v, -1) >= GOLD_THRESHOLD},
        "labels": labels,
    }


def select(queries, include_partial):
    """Split the set into exportable entries and skipped ones (with the reason, which is
    printed rather than swallowed — a silent drop reads as 'covered everything')."""
    keep, dropped = [], []
    for qid in sorted(queries):
        s = summarize(queries[qid])
        if not include_partial and s["decided"] < s["pool_size"]:
            dropped.append((qid, s["text"],
                            f"incomplete — {s['decided']}/{s['pool_size']} decided; "
                            f"query_class needs the complete relevant set"))
        elif not s["relevant"]:
            dropped.append((qid, s["text"],
                            "no relevant documents — gold_ids: [] cannot be satisfied"))
        else:
            keep.append((qid, s))
    return keep, dropped


def write_topics(path, keep):
    def render(f):
        for qid, s in keep:
            f.write(f"{qid}\t{s['text']}\n")
    atomic_write(path, render)


def write_qrels(path, keep):
    def render(f):
        for qid, s in keep:
            for cid, label in sorted(s["labels"].items(), key=lambda kv: int(kv[0])):
                if label in REL:                     # skips omitted
                    f.write(f"{qid} 0 {int(cid)} {REL[label]}\n")
    atomic_write(path, render)


def enrich(conn, query, golds):
    """query_type / difficulty measured the same way the rest of the golden set got
    them, so labeled entries stay comparable with the generated ones."""
    import filter_eval_candidates as fec
    from hybrid_search import core as h
    rl = fec.rank_of(h.lexical(conn, query, h.POOL), golds)
    rv = fec.rank_of(h.vector(conn, query, h.POOL), golds)
    rh = fec.rank_of(h.hybrid_split(conn, query, query, h.POOL), golds)
    return {"query_type": fec.classify(rl, rv, h.POOL), "difficulty": fec.difficulty(rh),
            "diag": {"lex_rank": rl, "vec_rank": rv, "hyb_rank": rh}}


def record_for(qid, s, set_name, extras):
    """One golden-set-shaped entry. Same shape whether it lands in the set's own file or
    (opt-in) in golden_set.json, so scripts/eval.py can load either without a branch."""
    record = {
        "query": s["text"],
        "gold_ids": s["relevant"],
        # The graded gains nDCG was designed for. gold_ids stays the binarized view, so
        # every other metric — and every consumer that predates grading — is unaffected.
        "gold_grades": {str(c): g for c, g in sorted(s["grades"].items(),
                                                     key=lambda kv: int(kv[0]))},
        "query_class": "known_item" if len(s["relevant"]) == 1 else "topical",
        "rationale": f"human-labeled pool ({set_name}/{qid}): "
                     f"{len(s['relevant'])} relevant of {s['pool_size']} pooled",
        "review_status": "verified",
        "source": "labeled",
        "split": "train",
    }
    record.update(extras.get(qid, {}))
    return record


def write_set_file(path, keep, set_name, extras):
    """The set as a standalone eval deck. `id` mirrors the qid's number, so the set file,
    the topics file and the qrels file all line up on one identifier."""
    def render(f):
        entries = []
        for qid, s in keep:
            rec = record_for(qid, s, set_name, extras)
            rec["id"] = int(qid[1:]) if qid[1:].isdigit() else len(entries) + 1
            rec["qid"] = qid
            entries.append(rec)
        json.dump(entries, f, indent=2, ensure_ascii=False)
    atomic_write(path, render)


def origin_counts(keep):
    """How the TOPICS were authored — distinct from how they were judged, which is always
    by hand. A set mixing hand-typed and LLM-proposed topics has to say so: they are
    different populations, and anyone comparing two sets needs to know whether the
    difference is in the retriever or in where the queries came from.

    Topics predating provenance tracking have no `origin` and are counted as human, which
    is what they are — the field was added with LLM proposals, not before them."""
    counts = {}
    for _, entry in keep:
        origin = entry.get("origin") or "human"
        counts[origin] = counts.get(origin, 0) + 1
    return dict(sorted(counts.items()))


def write_manifest(path, set_name, meta, keep, files):
    """Provenance per set. Which retrievers built the pool and how deep is what tells a
    later reader how reusable these judgments are: a depth-10, 2-leg pool cannot fairly
    judge a system that retrieves documents neither leg ever surfaced."""
    manifest = {}
    if os.path.exists(path):
        try:
            manifest = json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    manifest[set_name] = {
        "queries": len(keep),
        "judgments": sum(1 for _, s in keep for v in s["labels"].values() if v in REL),
        "scale": SCALE,
        "levels": {name: grade for name, grade in sorted(REL.items(), key=lambda kv: -kv[1])},
        "relevance": "graded 0-2 (2=highly relevant, 1=relevant, 0=not relevant; "
                     "skips omitted — a skip is a gap, not a 0)",
        "binarization": f"gold_ids = grade >= {GOLD_THRESHOLD}",
        "method": "pooled human judgment, rank discarded",
        "topic_origins": origin_counts(keep),
        **{k: v for k, v in (meta or {}).items()},
        "files": {k: os.path.relpath(v, REPO) for k, v in files.items()},
    }
    atomic_write(path, lambda f: json.dump(manifest, f, indent=2, ensure_ascii=False,
                                           sort_keys=True))


def merge_golden(golden_path, keep, set_name, extras):
    """Append new entries, upgrade existing ones in place.

    A labeled query that already exists (as a 'silver' guess, say) keeps its id and has
    its gold_ids replaced — appending a second entry for the same query would double-count
    it in every metric computed over the set."""
    golden = []
    if os.path.exists(golden_path):
        golden = json.load(open(golden_path, encoding="utf-8"))
        golden = golden["queries"] if isinstance(golden, dict) else golden
    # max()+1, not len()+1: this set spans ids 1-124 with 118 entries, so len()+1 collides.
    next_id = max((e.get("id", 0) for e in golden), default=0) + 1
    index = {norm(e.get("query")): i for i, e in enumerate(golden)}

    added, upgraded = [], []
    for qid, s in keep:
        record = record_for(qid, s, set_name, extras)
        key = norm(s["text"])
        if key in index:
            i = index[key]
            record["id"] = golden[i].get("id", next_id)
            merged = dict(golden[i])
            merged.update(record)
            golden[i] = merged
            upgraded.append((qid, record["id"]))
        else:
            record["id"] = next_id
            index[key] = len(golden)
            golden.append(record)
            added.append((qid, next_id))
            next_id += 1

    atomic_write(golden_path,
                 lambda f: json.dump(golden, f, indent=2, ensure_ascii=False))
    return golden, added, upgraded


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", dest="set_name", default=os.environ.get("JUDGMENTS_SET", "pooled_v1"))
    ap.add_argument("--store", default=os.environ.get("JUDGMENTS_PATH", DEFAULT_STORE))
    ap.add_argument("--golden", default=DEFAULT_GOLDEN)
    ap.add_argument("--topics-dir", default=TOPICS_DIR)
    ap.add_argument("--qrels-dir", default=QRELS_DIR)
    ap.add_argument("--sets-dir", default=SETS_DIR)
    ap.add_argument("--merge-golden", action="store_true",
                    help="ALSO merge these entries into golden_set.json. Off by default: "
                         "human-judged and synthetic sets are separate assessment efforts, "
                         "and combining them means neither can be reported alone.")
    ap.add_argument("--list-sets", action="store_true",
                    help="list every test set in the store and exit; writes nothing")
    ap.add_argument("--report", action="store_true",
                    help="dry run: print per-query status and what would be skipped; write nothing")
    ap.add_argument("--include-partial", action="store_true",
                    help="export incomplete queries too (query_class may be wrong)")
    ap.add_argument("--no-db", action="store_true",
                    help="skip query_type/difficulty enrichment (no Db2 connection)")
    args = ap.parse_args()

    if args.list_sets:
        store = load_store(args.store)
        print(f"{len(store['sets'])} set(s) in {os.path.relpath(args.store, REPO)}:",
              file=sys.stderr)
        for name, set_ in sorted(store["sets"].items()):
            members = [q for q in (set_.get("members") or []) if q in store["queries"]]
            keep_n, _ = select({q: store["queries"][q] for q in members}, False)
            n_j = sum(len(store["queries"][q].get("labels") or {}) for q in members)
            print(f"  {name:20} {len(members):3} queries · {n_j:4} judgments · "
                  f"{len(keep_n)} exportable", file=sys.stderr)
        return

    meta, queries = load_set(args.store, args.set_name)
    keep, dropped = select(queries, args.include_partial)

    print(f"set {args.set_name!r}: {len(queries)} queries, "
          f"{len(keep)} exportable, {len(dropped)} skipped", file=sys.stderr)
    for qid, s in keep:
        print(f"  OK      {qid}  {s['decided']}/{s['pool_size']} decided · "
              f"{len(s['relevant'])} relevant · {s['skipped']} skipped  {s['text']!r}",
              file=sys.stderr)
    for qid, text, why in dropped:
        print(f"  SKIP    {qid}  {text!r}: {why}", file=sys.stderr)

    if args.report:
        print("\n--report: nothing written.", file=sys.stderr)
        return
    if not keep:
        print("\nnothing exportable — no files written.", file=sys.stderr)
        return

    extras = {}
    if not args.no_db:
        try:
            from hybrid_search import core as h
            import ibm_db
            conn = h.connect()
            try:
                for qid, s in keep:
                    extras[qid] = enrich(conn, s["text"], s["relevant"])
            finally:
                ibm_db.close(conn)
        except Exception as e:
            # Not fatal: the entry is still correct without them, and saying so is better
            # than emitting a query_type nobody measured.
            print(f"WARNING: no Db2 connection ({type(e).__name__}: {e}) — "
                  f"query_type/difficulty omitted.", file=sys.stderr)

    topics = os.path.join(args.topics_dir, f"{args.set_name}.tsv")
    qrels = os.path.join(args.qrels_dir, f"{args.set_name}.qrels")
    setfile = os.path.join(args.sets_dir, f"{args.set_name}.json")
    manifest = os.path.join(args.sets_dir, "manifest.json")
    write_topics(topics, keep)
    write_qrels(qrels, keep)
    write_set_file(setfile, keep, args.set_name, extras)
    write_manifest(manifest, args.set_name, meta, keep,
                   {"topics": topics, "qrels": qrels, "eval_set": setfile})

    n_qrels = sum(1 for _, s in keep for v in s["labels"].values() if v in REL)
    rel = lambda p: os.path.relpath(p, REPO)
    print(f"\nwrote {len(keep)} topics      -> {rel(topics)}", file=sys.stderr)
    print(f"wrote {n_qrels} qrels lines -> {rel(qrels)}", file=sys.stderr)
    print(f"wrote {len(keep)} entries     -> {rel(setfile)}", file=sys.stderr)
    print(f"updated provenance    -> {rel(manifest)}", file=sys.stderr)
    print(f"\ngolden_set.json NOT touched (separate assessment effort). Evaluate this set:"
          f"\n  PYTHONPATH=src DB2_HOST=local python scripts/eval.py {rel(setfile)}",
          file=sys.stderr)

    if args.merge_golden:
        golden, added, upgraded = merge_golden(args.golden, keep, args.set_name, extras)
        print(f"\n--merge-golden: {len(golden)} entries "
              f"({len(added)} added, {len(upgraded)} upgraded in place) "
              f"-> {rel(args.golden)}", file=sys.stderr)
        for qid, gid in added:
            print(f"  + id {gid}  from {qid}", file=sys.stderr)
        for qid, gid in upgraded:
            print(f"  ^ id {gid}  upgraded from {qid} (already in the golden set)",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
