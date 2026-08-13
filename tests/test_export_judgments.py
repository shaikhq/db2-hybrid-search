#!/usr/bin/env python3
"""Tests for scripts/export_judgments.py — judgments -> topics + qrels + golden_set.

Driven from a fixture store, so no Db2 is needed (the exporter runs with --no-db; the
query_type/difficulty enrichment is the only part that connects).

The cases here are the ones that fail SILENTLY in production: an id collision, a
double-counted query, a query_class computed from a partial relevant set. None of them
raise; they just quietly produce a wrong eval set.

Run: PYTHONPATH=src .venv/bin/python tests/test_export_judgments.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "src"))

import export_judgments as ex   # noqa: E402

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond else f"  << {detail}"))


# q001 complete/topical (with a skip), q002 complete/known_item whose text already exists
# in the golden set, q003 incomplete, q004 all-irrelevant.
# v3 membership model: judgments live once under "queries"; a set is a named list of
# qids. q001 is deliberately filed into TWO sets — exporting both must produce the same
# grades from that single stored judgment.
STORE = {
  "queries": {
    "q001": {"text": "managing stress", "pool_size": 4,
             "labels": {"10": "highly_relevant", "11": "relevant",
                        "12": "irrelevant", "13": "skip"}},
    "q002": {"text": "atomic habits", "pool_size": 2,
             "labels": {"20": "relevant", "21": "irrelevant"}},
    "q003": {"text": "half judged", "pool_size": 10,
             "labels": {"30": "relevant", "31": "irrelevant", "32": "irrelevant"}},
    "q004": {"text": "nothing relevant", "pool_size": 2,
             "labels": {"40": "irrelevant", "41": "irrelevant"}},
  },
  "sets": {
    "pooled_v1": {"assessor": "t", "pool_depth": 10, "legs": ["lexical", "vector"],
                  "members": ["q001", "q002", "q003", "q004"]},
    "stress_probe": {"pool_depth": 10, "members": ["q001"]},
  },
}

# ids 1, 2, 124 — gaps on purpose: len()+1 would be 4, max()+1 is 125.
GOLDEN = [
    {"id": 1, "query": "influence expanded edition", "gold_ids": [1],
     "source": "silver", "review_status": "needs_review", "split": "train"},
    {"id": 2, "query": "Atomic  HABITS", "gold_ids": [999], "difficulty": "hard",
     "source": "silver", "review_status": "needs_review", "split": "train"},
    {"id": 124, "query": "something else", "gold_ids": [7],
     "source": "silver", "review_status": "needs_review", "split": "holdout"},
]


def fixture():
    d = tempfile.mkdtemp(prefix="export-test-")
    store, golden = os.path.join(d, "judgments.json"), os.path.join(d, "golden_set.json")
    json.dump(STORE, open(store, "w"))
    json.dump(GOLDEN, open(golden, "w"))
    return d, store, golden


def run(d, store, golden, *extra):
    cmd = [sys.executable, os.path.join(REPO, "scripts", "export_judgments.py"),
           "--store", store, "--golden", golden, "--no-db",
           "--topics-dir", os.path.join(d, "topics"),
           "--qrels-dir", os.path.join(d, "qrels"),
           "--sets-dir", os.path.join(d, "sets"), *extra]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": os.path.join(REPO, "src")})
    return p


print("\nselection guards:")
keep, dropped = ex.select(STORE["queries"], include_partial=False)
check("complete, has-relevant queries are exportable",
      [q for q, _ in keep] == ["q001", "q002"], [q for q, _ in keep])
check("incomplete query skipped (query_class needs the full relevant set)",
      any(q == "q003" and "incomplete" in why for q, _, why in dropped), dropped)
check("zero-relevant query skipped (gold_ids: [] is unsatisfiable)",
      any(q == "q004" and "no relevant" in why for q, _, why in dropped), dropped)
keep_p, _ = ex.select(STORE["queries"], include_partial=True)
check("--include-partial admits the incomplete query",
      "q003" in [q for q, _ in keep_p], [q for q, _ in keep_p])
check("--include-partial still drops the zero-relevant one",
      "q004" not in [q for q, _ in keep_p], [q for q, _ in keep_p])

print("\nend-to-end export:")
d, store, golden = fixture()
p = run(d, store, golden)
check("exporter exits 0", p.returncode == 0, p.stderr[-400:])

topics = open(os.path.join(d, "topics", "pooled_v1.tsv")).read().splitlines()
check("topics file is qid<TAB>text, one line per exported query",
      topics == ["q001\tmanaging stress", "q002\tatomic habits"], topics)

qrels = [l.split() for l in
         open(os.path.join(d, "qrels", "pooled_v1.qrels")).read().splitlines()]
check("every qrels line is a 4-column TREC record",
      all(len(r) == 4 for r in qrels) and qrels, qrels)
check("column 2 is the literal 0 (TREC's vestigial iteration field)",
      all(r[1] == "0" for r in qrels), qrels)
# Graded qrels: the grade itself is written, not a collapsed 0/1. This is the whole
# point of grading — nDCG reads these numbers as gain.
check("qrels carry the grade (2 / 1 / 0), not a binarized 0/1",
      sorted((r[0], r[2], r[3]) for r in qrels) ==
      [("q001", "10", "2"), ("q001", "11", "1"), ("q001", "12", "0"),
       ("q002", "20", "1"), ("q002", "21", "0")], sorted(qrels))
check("both a 2 and a 1 are present and distinct",
      {r[3] for r in qrels} == {"0", "1", "2"}, {r[3] for r in qrels})
check("skips are omitted (a skip is a gap, not a non-relevance judgment)",
      not any(r[2] == "13" for r in qrels), qrels)

# The separation that matters: a human-judged set is its own assessment effort. Mixing it
# into the synthetic deck means neither can be reported alone.
print("\nseparation from the synthetic golden set:")
check("golden_set.json is NOT touched by default",
      json.load(open(golden)) == GOLDEN, "golden_set was modified")

sf = json.load(open(os.path.join(d, "sets", "pooled_v1.json")))
by_id = {e["id"]: e for e in sf}
check("the set is written as its own standalone eval deck", len(sf) == 2, len(sf))
check("set-file ids mirror the qid numbers (set/topics/qrels line up)",
      sorted(by_id) == [1, 2] and by_id[1]["qid"] == "q001", [e.get("qid") for e in sf])
check("gold_ids binarizes at grade >= 1 (MRR/Recall stay comparable)",
      by_id[1]["gold_ids"] == [10, 11], by_id[1].get("gold_ids"))
check("gold_grades carries the graded gains nDCG needs",
      by_id[1]["gold_grades"] == {"10": 2, "11": 1}, by_id[1].get("gold_grades"))
check("grade-0 documents are not gold", 12 not in by_id[1]["gold_ids"], by_id[1])
check("2 relevant -> topical", by_id[1]["query_class"] == "topical", by_id[1])
check("1 relevant -> known_item", by_id[2]["query_class"] == "known_item", by_id[2])
check("entries are marked verified/labeled",
      all(e["source"] == "labeled" and e["review_status"] == "verified" for e in sf), sf)
check("set file is golden-set shaped (a list eval.py can load directly)",
      isinstance(sf, list) and all({"id", "query", "gold_ids", "split"} <= set(e)
                                   for e in sf), sf)

man = json.load(open(os.path.join(d, "sets", "manifest.json")))
check("manifest records the scale and how gold_ids was binarized",
      man["pooled_v1"]["scale"] == "graded3"
      and man["pooled_v1"]["levels"]["highly_relevant"] == 2
      and "grade >= 1" in man["pooled_v1"]["binarization"], man["pooled_v1"])
check("manifest records provenance for the set",
      man["pooled_v1"]["queries"] == 2 and man["pooled_v1"]["judgments"] == 5
      and man["pooled_v1"]["pool_depth"] == 10
      and man["pooled_v1"]["legs"] == ["lexical", "vector"], man)

print("\n--merge-golden (opt-in only):")
dm, storem, goldenm = fixture()
run(dm, storem, goldenm, "--merge-golden")
gm = json.load(open(goldenm))
mid = {e["id"]: e for e in gm}
check("opt-in merge adds one entry and upgrades the other", len(gm) == 4, len(gm))
check("new entry id continues from max(id)+1, not len()+1",
      125 in mid and 4 not in mid, sorted(mid))
check("existing query upgraded in place, keeping its id (no double-count)",
      mid[2]["gold_ids"] == [20] and mid[2]["source"] == "labeled", mid[2])
check("upgrade preserves fields the exporter does not own",
      mid[2].get("difficulty") == "hard", mid[2])
check("untouched entries are not clobbered",
      mid[1]["gold_ids"] == [1] and mid[1]["source"] == "silver"
      and mid[124]["split"] == "holdout", [mid[1], mid[124]])

print("\nidempotence + report mode:")
run(d, store, golden)
check("re-running leaves the standalone set unchanged",
      json.load(open(os.path.join(d, "sets", "pooled_v1.json"))) == sf, "set file drifted")
check("re-running still does not touch golden_set.json",
      json.load(open(golden)) == GOLDEN, "golden_set was modified")
run(dm, storem, goldenm, "--merge-golden")
gm2 = json.load(open(goldenm))
check("re-running --merge-golden adds no duplicates", len(gm2) == 4, len(gm2))
check("re-running --merge-golden keeps ids stable",
      sorted(e["id"] for e in gm2) == [1, 2, 124, 125], sorted(e["id"] for e in gm2))

d3, store3, golden3 = fixture()
p3 = run(d3, store3, golden3, "--report")
check("--report exits 0", p3.returncode == 0, p3.stderr[-300:])
check("--report writes nothing", not os.path.exists(os.path.join(d3, "topics"))
      and not os.path.exists(os.path.join(d3, "sets"))
      and json.load(open(golden3)) == GOLDEN, os.listdir(d3))
check("--report names each skipped query and why",
      "q003" in p3.stderr and "incomplete" in p3.stderr
      and "q004" in p3.stderr and "no relevant" in p3.stderr, p3.stderr[-400:])

# ---- membership: one judgment, many sets ----
# The property the copying model could not give: q001 is in two sets, judged once.
print("\nmembership (one judgment, many sets):")
d4, store4, golden4 = fixture()
run(d4, store4, golden4)
run(d4, store4, golden4, "--set", "stress_probe")
qa = open(os.path.join(d4, "qrels", "pooled_v1.qrels")).read().splitlines()
qb = open(os.path.join(d4, "qrels", "stress_probe.qrels")).read().splitlines()
check("a query filed in two sets exports into both",
      any(l.startswith("q001 ") for l in qa) and any(l.startswith("q001 ") for l in qb),
      (qa[:2], qb[:2]))
check("both sets carry identical grades from the one stored judgment",
      [l for l in qa if l.startswith("q001 ")] == qb, (qa, qb))
check("the second set exports only its own members",
      {l.split()[0] for l in qb} == {"q001"}, {l.split()[0] for l in qb})

meta_a, q_a = ex.load_set(store4, "pooled_v1")
meta_b, q_b = ex.load_set(store4, "stress_probe")
check("load_set resolves members against the shared queries",
      list(q_b) == ["q001"], list(q_b))
check("the same judgment backs both sets",
      q_a["q001"]["labels"] == q_b["q001"]["labels"], q_b["q001"]["labels"])

# Backward compatibility: v1 (text-keyed) and v2 (set-owned) stores still export.
print("\nbackward compatibility:")
for _name, _raw in (
    ("v1", {"queries": {"managing stress": {"pool_size": 2,
            "labels": {"10": "relevant", "11": "irrelevant"}}}}),
    ("v2", {"sets": {"pooled_v1": {"pool_depth": 10, "queries": {"q001": {
            "text": "managing stress", "pool_size": 2,
            "labels": {"10": "relevant", "11": "irrelevant"}}}}}}),
):
    _d = tempfile.mkdtemp(prefix=f"export-{_name}-")
    _sp = os.path.join(_d, "judgments.json"); json.dump(_raw, open(_sp, "w"))
    _gp = os.path.join(_d, "golden_set.json"); json.dump(GOLDEN, open(_gp, "w"))
    _p = run(_d, _sp, _gp)
    _lines = (open(os.path.join(_d, "qrels", "pooled_v1.qrels")).read().splitlines()
              if _p.returncode == 0 else [])
    check(f"{_name} store still exports (old backups stay usable)",
          _p.returncode == 0 and len(_lines) == 2, _p.stderr[-200:])

print("\n--list-sets:")
d5, store5, golden5 = fixture()
p5 = run(d5, store5, golden5, "--list-sets")
check("--list-sets names every set", p5.returncode == 0
      and "pooled_v1" in p5.stderr and "stress_probe" in p5.stderr, p5.stderr[-300:])
check("--list-sets writes nothing", not os.path.exists(os.path.join(d5, "sets")),
      os.listdir(d5))

print(f"\n{'='*54}\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILURES:", FAIL); sys.exit(1)
print("ALL GREEN")
