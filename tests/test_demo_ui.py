#!/usr/bin/env python3
"""Phase-2 D/E/F for the demo page:
  - static structural + a11y/responsive assertions (fixture-based, deterministic)
  - FastAPI TestClient smoke (substitutes headless-browser E2E, which this env lacks)
  - regression: existing pages/endpoints still serve

Run: PYTHONPATH=src DB2_HOST=local .venv/bin/python tests/test_demo_ui.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
UI = os.path.join(REPO, "ui")
STATIC = os.path.join(UI, "static")
sys.path.insert(0, UI)
sys.path.insert(0, os.path.join(REPO, "src"))

PASS, FAIL, SKIP = [], [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond else f"  << {detail}"))
def read(p): return open(p).read()

idx = read(os.path.join(STATIC, "index.html"))
appjs = read(os.path.join(STATIC, "app.js"))
demojs = read(os.path.join(STATIC, "demo.js"))
css = read(os.path.join(STATIC, "styles.css"))

# ---------------- F + registration: static structure / a11y / responsive ----------------
print("\nF + registration (static):")
check("index.html registers demo tab", 'data-page="demo"' in idx)
check("index.html has #page-demo section", 'id="page-demo"' in idx)
check("index.html loads demo.js", 'src="demo.js' in idx)  # tolerate ?v= cache-bust
check("app.js setPage is generic (registers new pages)", '[id^="page-"]' in appjs)
check("demo.js renders verdict icon + text (color not sole signal)",
      "icon:" in demojs and "label:" in demojs and 'aria-hidden="true"' in demojs)
check("verdict classes styled distinctly", all(c in css for c in
      [".dpanel-found", ".dpanel-wrong", ".dpanel-nothing"]))
check("responsive: max-width 640px media query", "max-width: 640px" in css or "max-width:640px" in css)
check("responsive: 3-column panels grid", "repeat(3, 1fr)" in css or "repeat(3,1fr)" in css)
check("a11y: ARIA roles/labels present on demo controls",
      'role="group"' in idx and 'aria-label="example queries"' in idx and 'aria-live="polite"' in idx)
check("a11y: keyboard/focus — chips focus-visible styled", ".dchip:focus-visible" in css)
check("a11y: screen-reader-only class defined", ".sr-only" in css and "sr-only" in demojs)
check("matrix (queries x methods) rendered for narrow view", "dsb-matrix" in demojs and ".dsb-matrix" in css)
check("demo has a Shuffle control", 'id="demo-shuffle"' in idx and "shuffleDeck" in demojs)
check("shuffle resets the scoreboard", "resetSession" in demojs and "D.seen.clear()" in demojs)
check("demo has a Representative-set control", 'id="demo-representative"' in idx and "loadRepresentative" in demojs)
# terminology: "Keyword" is the Search-tab mode label (user-chosen); raw BM25/Vector
# are still never surfaced as UI labels.
appjs = read(os.path.join(STATIC, "app.js"))
for bad in (">BM25<", ">Vector<", '"BM25"', '"Vector"'):
    check(f"no leg label {bad!r} in app.js/demo.js/index.html",
          bad not in appjs and bad not in demojs and bad not in idx, bad)
check("lexical results are highlighted (highlight+queryTerms wired)",
      "function highlight" in appjs and "queryTerms" in appjs and "highlight(esc(" in appjs)
check("<mark> styled for highlights", "mark {" in css or "mark{" in css)
# honesty in the renderer: no 'hybrid ranked best' language, no per-query hardcoding
check("no 'ranked best' language in demo.js", "ranked best" not in demojs.lower())
check("demo.js has no hardcoded book titles (renders from data)",
      "Psychology of Money" not in demojs and "Atomic Habits" not in demojs)

# ---------------- Evaluate tab (replaces "Golden eval set") ----------------
print("\nEvaluate tab (static):")
EVAL_JS = os.path.join(STATIC, "evaluate.js")
evaljs = read(EVAL_JS) if os.path.exists(EVAL_JS) else ""
check("evaluate.js exists", bool(evaljs), EVAL_JS)
check("index.html registers the Evaluate tab", 'data-page="evaluate"' in idx)
check("index.html has #page-evaluate section", 'id="page-evaluate"' in idx)
check("index.html loads evaluate.js", 'src="evaluate.js' in idx)
check("evaluate.js defines evaluateBoot()", "function evaluateBoot" in evaljs)
# Golden eval set is gone -- and so is the listener that would crash without it.
check("Golden eval set tab removed", 'data-page="eval"' not in idx and 'id="page-eval"' not in idx)
check("app.js no longer binds #eval-list (an unguarded listener would throw in wire())",
      "#eval-list" not in appjs and "renderEval" not in appjs)
check("app.js no longer fetches eval_set.json", "eval_set.json" not in appjs)
# The one rule this tab exists to enforce: it renders numbers, it does not compute them.
check("evaluate.js computes no metrics of its own",
      "Math.log2" not in evaljs and "/api/evaluate" in evaljs)
check("evaluate.js reads the available sets from the backend", "/api/eval_sets" in evaljs)
check("per-query drill-down present (aggregates hide WHICH queries fail)",
      "per_query" in evaljs and "renderQueries" in evaljs)
check("offline: falls back to frozen eval_fixtures.json",
      "eval_fixtures.json" in evaljs)
check("null metrics render as a dash, not 0.000 (nan means 'not measured')",
      "evNum" in evaljs and '"\u2014"' in evaljs.replace("—", "\u2014"))
check("Evaluate styles defined", ".evaluatepage" in css and ".ev-table" in css)
# Regression: the Demo tab (the offline talk narrative) is untouched.
check("Demo tab still registered and still offline-capable",
      'data-page="demo"' in idx and "demo_fixtures.json" in demojs)

# ---------------- Label tab: static structure + interaction contract ----------------
# The contract these assert is docs/label-tab-plan.md, "Interaction contract (approved)".
print("\nLabel tab (static):")
LABEL_JS = os.path.join(STATIC, "label.js")
labeljs = read(LABEL_JS) if os.path.exists(LABEL_JS) else ""
check("label.js exists", bool(labeljs), LABEL_JS)
check("index.html registers label tab", 'data-page="label"' in idx)
check("index.html has #page-label section", 'id="page-label"' in idx)
check("index.html loads label.js", 'src="label.js' in idx)
check("label.js defines labelBoot()", "function labelBoot" in labeljs)
check("cache-bust bumped to v=60 everywhere", "?v=59" not in idx and "?v=60" in idx)
# Test sets: a set is a named LIST of qids, browsed from a sidebar in this same tab
# (reviewing a set IS re-labeling it, so it must not live behind another tab).
check("sidebar: set picker + New set + member list present",
      all(i in idx for i in ('id="label-set"', 'id="label-newset"',
                             'id="label-members"', 'id="label-setmeta"')))
check("sidebar reuses the Demo tab layout rather than a new one",
      "demo-layout" in idx.split('id="page-label"')[1] and ".demo-layout" in css)
check("\"Add to test set\" control is wired", 'id="label-add"' in idx
      and 'id="label-addset"' in idx and "addToSet" in labeljs)
check("sidebar reads GET /api/sets", "/api/sets" in labeljs and "loadSets" in labeljs)
check("membership adds a reference, never a copy of the judgments",
      "/members" in labeljs and "no copy" in labeljs)
check("keyboard grades are suppressed while a SELECT has focus",
      '"SELECT"' in labeljs)
# contract 1: labeled cards collapse in place (they are NOT removed from the list)
check("contract 1: collapsed-label state exists (.lcard-labeled)",
      ".lcard-labeled" in css and "lcard-labeled" in labeljs)
# Graded relevance: the key IS the grade (2/1/0), so the scale stays in front of the
# assessor while judging. See ui/api.py GRADES.
check("graded scale: 2/1/0/s are bound to the three grades plus skip",
      all(k in labeljs for k in ('"2": "highly_relevant"', '"1": "relevant"',
                                 '"0": "irrelevant"', '"s": "skip"')), "LKEYS")
check("graded scale: the third level has its own collapse state + chip",
      ".lcard-highly_relevant" in css and ".lchip-highly_relevant" in css)
check("graded scale: progress breaks the grades out",
      "highly" in labeljs and "relevant" in labeljs)
check("contract 1: keyboard path wired (keydown handler)", "keydown" in labeljs)
# contract 3: pools rehydrate from the judgments store, not from session clicks
check("contract 3: rehydrates from /api/judgments", "/api/judgments" in labeljs)
# contract 4: two numbers — decided/pool plus a separate skipped count
check("contract 4: progress tracks decided and skipped separately",
      "decided" in labeljs and "skipped" in labeljs)
# contract 5: empty/partial pools are explicit states
check("contract 5: empty-pool state is rendered, not a blank list",
      "nothing to label" in labeljs.lower())
check("contract 5: partial-leg (1 of 2 retrievers) state is rendered",
      "retriever" in labeljs.lower())
# anti-anchoring: no PER-DOCUMENT provenance in the labeling UI. Aggregate per-leg
# counts are legitimately read (contract 5's "1 of 2 retrievers" needs them); what must
# never reach a card is a position badge or a leg chip. app.js's resultCard() renders a
# position badge, so reusing it here would both anchor the assessor and print
# "undefined" — the pool carries no such field by design.
# Comments are stripped first: label.js *documents* why it avoids resultCard(), and a
# raw substring match would read that explanation as a violation. (No "//" appears
# inside a string literal in label.js, so line-stripping is safe here.)
_labelcode = re.sub(r"//.*", "", labeljs)
check("anti-anchoring: no per-document position or leg badge on label cards",
      'class="rank"' not in _labelcode and "legChip" not in _labelcode
      and "resultCard(" not in _labelcode)

# ---------------- D-substitute + E: TestClient smoke ----------------
print("\nD (TestClient smoke) + E (regression):")
try:
    from fastapi.testclient import TestClient
    import api  # noqa
    client = TestClient(api.app)
    have_client = True
except Exception as e:
    have_client = False
    SKIP.append(f"TestClient unavailable: {type(e).__name__}: {e}")
    print(f"  [SKIP] FastAPI TestClient — {e}")

if have_client:
    # page loads and references the demo assets
    r = client.get("/")
    check("GET / -> 200 (index served)", r.status_code == 200)
    check("index HTML includes demo page + script", "page-demo" in r.text and "demo.js" in r.text)
    # static assets serve (new + existing = regression)
    for path in ("/demo.js", "/demo_fixtures.json", "/app.js", "/fixtures.json", "/styles.css", "/eval_set.json"):
        code = client.get(path).status_code
        check(f"GET {path} -> 200", code == 200, code)
    # new API: deck
    r = client.get("/api/demo_deck")
    check("GET /api/demo_deck -> 200 list", r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) >= 1, r.status_code)
    # regression: existing endpoints still present
    check("regression: /api/queries still 200", client.get("/api/queries").status_code == 200)
    # live demo endpoint (hits Db2) — smoke, guarded
    try:
        r = client.get("/api/demo", params={"q": "teddy hamilton"})
        if r.status_code == 200:
            vm = r.json()
            ok = set(vm.get("strategies", {})) == {"lexical", "vector", "hybrid"} and \
                 all("verdict" in vm["strategies"][s] for s in ("lexical", "vector", "hybrid"))
            check("GET /api/demo?q=... -> view_model with 3 verdicts (live)", ok, vm.get("strategies", {}).keys())
        else:
            SKIP.append(f"/api/demo returned {r.status_code} (Db2 not reachable?)")
            print(f"  [SKIP] /api/demo live — status {r.status_code}")
    except Exception as e:
        SKIP.append(f"/api/demo live errored: {e}")
        print(f"  [SKIP] /api/demo live — {e}")
    # open-ended Search backend: 3 strategies with result lists
    try:
        r = client.get("/api/search", params={"q": "atomic habits"})
        if r.status_code == 200:
            j = r.json()
            ok = all(k in j for k in ("lexical", "vector", "hybrid")) and \
                 isinstance(j["lexical"].get("results"), list)
            check("GET /api/search?q=... -> 3 strategies with results (open-ended)", ok, list(j.keys()))
        else:
            SKIP.append(f"/api/search returned {r.status_code}")
            print(f"  [SKIP] /api/search live — status {r.status_code}")
    except Exception as e:
        SKIP.append(f"/api/search live errored: {e}")
        print(f"  [SKIP] /api/search live — {e}")

# ---------------- Label tab: pool building + judgments store ----------------
# Pool building is tested as a pure function (no Db2): dedup, rank-discard and the
# md5(q)-seeded shuffle are exactly the parts that fail silently in the UI and only
# show up later as unexplainable eval numbers. The live /api/pool smoke is guarded.
print("\nLabel tab (pool + judgments):")
if have_client:
    import json as _json
    import tempfile

    _tmpdir = tempfile.mkdtemp(prefix="judgments-test-")
    _store = os.path.join(_tmpdir, "judgments.json")
    # Resolved per call, so this redirect protects the real data/eval/judgments.json.
    os.environ["JUDGMENTS_PATH"] = _store
    check("JUDGMENTS_PATH resolves per call (real store untouched)",
          hasattr(api, "_judgments_path") and api._judgments_path() == _store,
          getattr(api, "_judgments_path", lambda: "missing")())

    Q = "how to build better habits"
    lex = [(66, 9.1), (39, 8.0), (12, 7.2), (5, 6.4)]
    vec = [(39, 0.91), (63, 0.88), (7, 0.80), (66, 0.77)]
    pool = api.build_pool(Q, lex, vec)
    check("pool unions both legs and dedups by chunk id",
          sorted(pool) == [5, 7, 12, 39, 63, 66], sorted(pool))
    check("pool is deterministic for the same query (resume-stable order)",
          api.build_pool(Q, lex, vec) == pool, pool)
    check("pool order is seeded on the query (different query -> different order)",
          api.build_pool("something else entirely", lex, vec) != pool)
    check("pool discards rank (plain chunk ids, no score/leg carried through)",
          all(isinstance(c, int) for c in pool), pool)
    check("pool order is neither leg's ranking",
          pool != [c for c, _ in lex] and pool != [c for c, _ in vec], pool)

    # judgments store: persist under a stable qid, overwrite-in-place, atomic write
    SET = api._set_name()
    # v3: judgments live at the top level; a set only references them by qid.
    entries = lambda: _json.load(open(_store))["queries"]

    r = client.post("/api/judgments",
                    json={"query": Q, "cid": 66, "label": "relevant", "pool_size": 6})
    check("POST /api/judgments -> 200", r.status_code == 200, r.status_code)
    QID = r.json().get("qid")
    check("POST assigns a qid", QID == "q001", QID)
    saved = entries()
    check("judgment persisted at sets[set].queries[qid].labels[cid]",
          saved[QID]["labels"]["66"] == "relevant", saved)
    check("query text stored as typed, alongside the qid",
          saved[QID]["text"] == Q, saved[QID].get("text"))
    check("pool_size recorded (exporter's completeness guard needs it)",
          saved[QID]["pool_size"] == 6, saved)

    client.post("/api/judgments",
                json={"query": Q, "cid": 39, "label": "skip", "pool_size": 6})
    r = client.post("/api/judgments",
                    json={"query": Q, "cid": 66, "label": "irrelevant", "pool_size": 6})
    labels = entries()[QID]["labels"]
    check("re-POST of the same (query, cid) overwrites, no duplicate",
          labels["66"] == "irrelevant" and len(labels) == 2, labels)

    # The reason qids exist: text is a display field, not an identity.
    r = client.post("/api/judgments",
                    json={"query": "  How To Build   BETTER Habits ", "cid": 12,
                          "label": "relevant", "pool_size": 6})
    check("case/whitespace variant resolves to the same qid (no duplicate entry)",
          r.json().get("qid") == QID and len(entries()) == 1, list(entries()))
    check("the variant's judgment lands on the original entry",
          entries()[QID]["labels"].get("12") == "relevant", entries()[QID]["labels"])
    check("qid is stable across writes",
          api._qid_for(_json.load(open(_store)), Q) == QID)

    # Graded relevance: three levels plus skip. gold_ids binarizes at grade >= 1, so the
    # older binary level names stay valid and only nDCG gains information.
    r = client.post("/api/judgments",
                    json={"query": Q, "cid": 5, "label": "highly_relevant",
                          "pool_size": 6})
    check("POST accepts the highly_relevant grade", r.status_code == 200, r.text[:200])
    check("POST returns a per-grade breakdown",
          r.json().get("counts", {}).get("highly_relevant") == 1
          and r.json().get("counts", {}).get("skip") == 1, r.json().get("counts"))
    check("the set records its relevance scale",
          _json.load(open(_store))["sets"][SET].get("scale") == "graded3",
          _json.load(open(_store))["sets"][SET].get("scale"))
    check("the set records membership, not judgments",
          "queries" not in _json.load(open(_store))["sets"][SET]
          and QID in _json.load(open(_store))["sets"][SET]["members"],
          _json.load(open(_store))["sets"][SET])
    check("all three grades plus skip are accepted",
          api.LABELS == {"irrelevant", "relevant", "highly_relevant", "skip"}, api.LABELS)
    check("grade values match the exporter's qrels mapping",
          api.GRADES == {"irrelevant": 0, "relevant": 1, "highly_relevant": 2}, api.GRADES)
    r = client.post("/api/judgments",
                    json={"query": Q, "cid": 7, "label": "somewhat", "pool_size": 6})
    check("an off-scale grade is still rejected", r.status_code == 400, r.status_code)

    check("atomic write leaves no temp residue beside the store",
          os.listdir(_tmpdir) == ["judgments.json"], os.listdir(_tmpdir))
    check("store stays parseable after every write", isinstance(labels, dict))

    r = client.post("/api/judgments",
                    json={"query": "zzz no results", "cid": 1,
                          "label": "relevant", "pool_size": 0})
    check("empty pool (pool_size 0) is rejected and writes no entry",
          r.status_code == 400 and len(entries()) == 1, r.status_code)

    r = client.get("/api/judgments")
    j = r.json()
    check("GET /api/judgments -> 200 with the active set", r.status_code == 200
          and j.get("set") == SET and QID in j.get("queries", {}), r.status_code)
    check("GET /api/judgments exposes a by_text index the UI can rehydrate from",
          j.get("by_text", {}).get(Q, {}).get("qid") == QID, list(j.get("by_text", {})))

    # v1 -> sets migration: the old store was keyed by query TEXT. Real judgments are
    # hand-produced and unrecoverable, so the conversion must be lossless.
    _oldtmp = tempfile.mkdtemp(prefix="judgments-v1-")
    _oldstore = os.path.join(_oldtmp, "judgments.json")
    with open(_oldstore, "w") as f:
        _json.dump({"queries": {"managing stress": {
            "pool_size": 15, "labels": {"19": "relevant", "2": "irrelevant"}}}}, f)
    os.environ["JUDGMENTS_PATH"] = _oldstore
    migrated = api._load_judgments()
    mq = migrated["queries"]
    check("v1 store migrates to sets/qid shape",
          list(mq) == ["q001"] and mq["q001"]["text"] == "managing stress", list(mq))
    check("migration preserves every label and the pool size",
          mq["q001"]["labels"] == {"19": "relevant", "2": "irrelevant"}
          and mq["q001"]["pool_size"] == 15, mq["q001"])
    client.post("/api/judgments", json={"query": "managing stress", "cid": 40,
                                        "label": "relevant", "pool_size": 15})
    check("first write after migration backs the v1 file up",
          os.path.exists(_oldstore + ".bak"), os.listdir(_oldtmp))
    check("post-migration write keeps the migrated labels",
          len(_json.load(open(_oldstore))["queries"]["q001"]["labels"]) == 3,
          _json.load(open(_oldstore)))
    os.environ["JUDGMENTS_PATH"] = _store       # restore for anything downstream

    # ---- test sets: membership, not ownership ----
    # A judgment is a fact about (query, document); a set is a named list of qids that
    # references it. This is what lets one query live in several sets, judged once.
    _setdir = tempfile.mkdtemp(prefix="judgments-sets-")
    _setstore = os.path.join(_setdir, "judgments.json")
    os.environ["JUDGMENTS_PATH"] = _setstore
    client.post("/api/judgments", json={"query": "managing stress", "cid": 19,
                                        "label": "highly_relevant", "pool_size": 3})
    client.post("/api/judgments", json={"query": "managing stress", "cid": 20,
                                        "label": "relevant", "pool_size": 3})
    store = lambda: _json.load(open(_setstore))
    check("judgments live at the top level, not inside a set",
          list(store()["queries"]) == ["q001"] and "queries" not in store()["sets"][SET],
          list(store()))
    check("judging a query files it into the active set",
          store()["sets"][SET]["members"] == ["q001"], store()["sets"][SET])

    r = client.post("/api/sets", json={"name": "stress_probe"})
    check("POST /api/sets creates a set", r.status_code == 200, r.text[:200])
    check("duplicate set name rejected",
          client.post("/api/sets", json={"name": "stress_probe"}).status_code == 400)
    check("path-unsafe set name rejected (names become filenames)",
          client.post("/api/sets", json={"name": "../etc"}).status_code == 400)

    r = client.post("/api/sets/stress_probe/members", json={"qid": "q001"})
    check("a query can be filed into a second set", r.status_code == 200, r.text[:200])
    check("membership is a reference — the judgments are NOT copied",
          len(store()["queries"]) == 1
          and store()["sets"]["stress_probe"]["members"] == ["q001"], store())
    check("adding twice is idempotent",
          client.post("/api/sets/stress_probe/members",
                      json={"qid": "q001"}).json()["members"] == ["q001"])
    check("filing an unknown qid 404s",
          client.post("/api/sets/stress_probe/members",
                      json={"qid": "q999"}).status_code == 404)

    # The payoff: correcting a grade once corrects it for every set.
    client.post("/api/judgments", json={"query": "managing stress", "cid": 19,
                                        "label": "relevant", "pool_size": 3})
    check("a correction reaches every set (one stored judgment, many references)",
          store()["queries"]["q001"]["labels"]["19"] == "relevant"
          and store()["sets"]["stress_probe"]["members"] == ["q001"], store()["queries"])

    r = client.delete("/api/sets/stress_probe/members/q001")
    check("unfiling removes membership only", r.status_code == 200
          and store()["sets"]["stress_probe"]["members"] == [], r.text[:200])
    check("unfiling KEEPS the judgments (they belong to the query, not the set)",
          len(store()["queries"]["q001"]["labels"]) == 2, store()["queries"])

    r = client.get("/api/sets")
    j = r.json()
    check("GET /api/sets summarises each member for the sidebar",
          j["sets"][SET]["queries"]["q001"]["decided"] == 2
          and j["sets"][SET]["queries"]["q001"]["gold"] == 2
          and j["sets"][SET]["judgments"] == 2, j["sets"][SET])
    check("GET /api/sets reports completeness per set",
          j["sets"][SET]["queries"]["q001"]["complete"] is False,
          j["sets"][SET]["queries"]["q001"])

    # v2 -> v3: the same query in two v2 sets collapses to one qid, referenced by both.
    _v2dir = tempfile.mkdtemp(prefix="judgments-v2-")
    _v2 = os.path.join(_v2dir, "judgments.json")
    with open(_v2, "w") as f:
        _json.dump({"sets": {
            "a": {"pool_depth": 10, "queries": {"q001": {
                "text": "managing stress", "pool_size": 3,
                "labels": {"19": "highly_relevant"}}}},
            "b": {"pool_depth": 10, "queries": {"q001": {
                "text": "Managing  STRESS", "pool_size": 3,
                "labels": {"20": "relevant"}}}}}}, f)
    os.environ["JUDGMENTS_PATH"] = _v2
    m = api._load_judgments()
    check("v2 -> v3 collapses a shared query to one qid",
          list(m["queries"]) == ["q001"], list(m["queries"]))
    check("v2 -> v3 keeps it referenced by both sets",
          m["sets"]["a"]["members"] == ["q001"] and m["sets"]["b"]["members"] == ["q001"],
          {k: v.get("members") for k, v in m["sets"].items()})
    check("v2 -> v3 merges both sets' labels onto the one query",
          m["queries"]["q001"]["labels"] == {"19": "highly_relevant", "20": "relevant"},
          m["queries"]["q001"]["labels"])
    client.post("/api/judgments", json={"query": "managing stress", "cid": 21,
                                        "label": "irrelevant", "pool_size": 3})
    check("first write after a v2 migration backs the old file up",
          os.path.exists(_v2 + ".bak"), os.listdir(_v2dir))
    os.environ["JUDGMENTS_PATH"] = _store

    # ---- Evaluate tab API ----
    r = client.get("/api/eval_sets")
    j = r.json()
    check("GET /api/eval_sets lists the labeled and synthetic decks",
          r.status_code == 200 and "golden_set" in j.get("sets", {}), list(j.get("sets", {})))
    check("eval_sets reports whether a deck carries grades",
          j["sets"]["golden_set"]["graded"] is False, j["sets"]["golden_set"])
    check("unknown set 404s", client.get("/api/evaluate", params={"set": "nope"}).status_code == 404)
    _fx = os.path.join(STATIC, "eval_fixtures.json")
    check("offline eval fixtures exist and parse",
          os.path.exists(_fx) and isinstance(_json.load(open(_fx)).get("sets"), dict), _fx)

    # live evaluation (hits Db2) — guarded like /api/demo
    try:
        r = client.get("/api/evaluate", params={"set": "golden_set"})
        if r.status_code == 200:
            j = r.json()
            b = j["blocks"]["all"]
            check("GET /api/evaluate -> three legs, four measures, per-query rows (live)",
                  set(j["legs"]) == {"lexical", "vector", "hybrid"}
                  and all(k in b["hybrid"] for k in ("mrr", "hits1", "recall", "ndcg"))
                  and len(j["per_query"]) == j["queries"], list(j))
            check("nan is serialised as null, not 0.0 (live)",
                  all(v is None or isinstance(v, (int, float))
                      for leg in j["legs"] for v in j["blocks"]["heldout"][leg].values()))
        else:
            SKIP.append(f"/api/evaluate returned {r.status_code}")
            print(f"  [SKIP] /api/evaluate live — status {r.status_code}")
    except Exception as e:
        SKIP.append(f"/api/evaluate live errored: {e}")
        print(f"  [SKIP] /api/evaluate live — {e}")

    # live pool endpoint (hits Db2) — guarded, same pattern as /api/demo above
    try:
        r = client.get("/api/pool", params={"q": "atomic habits"})
        if r.status_code == 200:
            j = r.json()
            first = (j.get("pool") or [{}])[0]
            check("GET /api/pool -> pool + per-leg counts (live)",
                  isinstance(j.get("pool"), list) and "legs" in j
                  and j.get("pool_size") == len(j["pool"]), list(j.keys()))
            check("live pool leaks no rank/score/leg per document (live)",
                  not ({"rank", "score", "leg"} & set(first)), list(first))
        else:
            SKIP.append(f"/api/pool returned {r.status_code} (Db2 not reachable?)")
            print(f"  [SKIP] /api/pool live — status {r.status_code}")
    except Exception as e:
        SKIP.append(f"/api/pool live errored: {e}")
        print(f"  [SKIP] /api/pool live — {e}")
else:
    print("  [SKIP] pool + judgments — TestClient unavailable")

print(f"\n{'='*54}\nRESULT: {len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
if SKIP:
    print("SKIPPED:", SKIP)
if FAIL:
    print("FAILURES:", FAIL); sys.exit(1)
print("ALL GREEN (with any skips noted above)")
