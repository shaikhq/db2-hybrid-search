#!/usr/bin/env python3
"""Topic generation — the guardrails, not the prose quality.

The feature exists to make test collections cheaper to build. The risk it carries is that
it quietly rebuilds golden_set: a set of queries the current retriever already answers,
which then agrees with that retriever forever. Three properties prevent that, and this
suite asserts all three:

  1. generation never sees document text  (only genres/pillar)
  2. generation never runs retrieval      (no consistency filtering)
  3. discards and edits are recorded      (the curation step stays auditable)

Run: DB2_HOST=local PYTHONPATH=src python tests/test_topicgen.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond else f"  << {detail}"))


from hybrid_search import topicgen as tg  # noqa: E402

# A corpus row whose text fields would be unmistakable if they ever leaked into a prompt.
POISON = "ZZTOPSECRETBOOKTEXT"
ROWS = [
    {"genres": "Business & Careers|Relationships", "pillar": "productivity",
     "chunk_text": POISON, "title": POISON, "authors": POISON, "description": POISON},
    {"genres": "Health & Wellness|Fitness", "pillar": "other",
     "chunk_text": POISON, "title": POISON, "description": POISON},
    {"genres": "Relationships", "pillar": "writing", "chunk_text": POISON},
]

print("1. generation is conditioned on themes, never on document text")
themes = tg.collection_profile(ROWS)
check("collection_profile returns themes", bool(themes), themes)
check("no document text in themes", not any(POISON in t for t in themes), themes)
check("'other' pillar dropped (61/92 here — no signal)", "other" not in themes)
check("pipe-separated genres split apart", "Relationships" in themes and "Fitness" in themes,
      themes)
prompt = tg.build_prompt(themes, 8)
check("no document text in the prompt", POISON not in prompt)
# The length distribution is enforced by issuing two single-style calls, NOT by asking
# one call for a mix — against the real 3B model every "mix" phrasing collapsed to one
# end (12/12 single words, or 10/10 full sentences). See the comment on SHORT_SHARE.
check("needs prompt asks for situations, not topic labels",
      "situation" in tg.build_prompt(themes, 8, style=tg.NEEDS_RULES))
check("concept prompt asks for separate spaced words",
      "SEPARATE words" in tg.build_prompt(themes, 8, style=tg.CONCEPT_RULES))
check("concept prompt forbids echoing the subject-area names back",
      "do NOT just repeat the subject-area" in tg.build_prompt(themes, 8,
                                                               style=tg.CONCEPT_RULES))
check("both styles still carry the no-generic-word rule",
      all('"grow"' in tg.build_prompt(themes, 8, style=s)
          for s in (tg.NEEDS_RULES, tg.CONCEPT_RULES)))
back = tg.build_prompt(themes, 5, backstory="just promoted, anxious about managing people")
check("backstory mode uses the backstory", "anxious about managing people" in back)
check("backstory mode still leaks no document text", POISON not in back)

print("\n2. generation runs no retrieval (no consistency filtering)")
# The failure this guards against is subtle: someone later "improves" generation by
# dropping candidates the engine cannot retrieve, which is exactly the mechanism that
# made golden_set agree with the retriever that built it. Make retrieval explode, and
# require generation to work anyway.
from hybrid_search import core as h  # noqa: E402

def _boom(*a, **k):
    raise AssertionError("retrieval called during topic generation")

h.lexical, h.vector, h.hybrid = _boom, _boom, _boom

captured = {}
def _fake_post(payload, timeout):
    captured["payload"] = payload
    queries = ["managing a team for the first time", "burnout", "how do I say no at work",
               "public speaking nerves", "managing a team for the first time"]  # dup at end
    return {"choices": [{"message": {"content": json.dumps({"queries": queries})}}]}

tg._post = _fake_post
try:
    out = tg.generate(themes, n=10)
    check("generate() succeeds with retrieval disabled", True)
except AssertionError as e:
    check("generate() succeeds with retrieval disabled", False, str(e))
    out = []

check("returns candidates", len(out) == 4, f"{len(out)} (expected 4 after dedup)")
check("exact duplicates collapsed", len({c["text"].lower() for c in out}) == len(out))
check("candidates carry no rank or score",
      all(set(c) == {"text", "theme"} for c in out), out[:1])
check("no document text sent to the model", POISON not in json.dumps(captured["payload"]))
check("sampled, not greedy (variety is the whole point)",
      captured["payload"]["temperature"] > 0, captured["payload"].get("temperature"))

print("\n3. parsing survives a model that ignores the grammar")
check("bare JSON array", tg._parse('["a","b"]') == ["a", "b"])
check("JSON wrapped in prose",
      tg._parse('Sure! {"queries": ["a", "b"]} hope that helps') == ["a", "b"])
check("newline fallback", tg._parse("a\nb") == ["a", "b"])
check("numbering stripped", tg._clean("1. managing stress") == "managing stress")
check("bullets stripped", tg._clean("- burnout") == "burnout")
check("quotes stripped", tg._clean('"public speaking"') == "public speaking")

print("\n3b. run-together tokens are repaired (every case observed from the live model)")
# The concept pass is TOLD to write separate spaced words and does — until it doesn't.
# These are the exact malformations Qwen2.5-3B produced across repeated live runs of the
# same prompt, so they are regression cases, not hypotheticals.
for src, want in [
    ("how-to-build-a-successful-business", "how to build a successful business"),
    ("small_business_taxes_help", "small business taxes help"),
    ("ProductivityStrategies", "Productivity Strategies"),
    ("Education&Learning", "Education Learning"),
    ("how_to_start_a_business small_business", "how to start a business small business"),
]:
    check(f"repaired {src[:28]!r}", tg._clean(src) == want, tg._clean(src))
# ...and the repair must not touch queries a person would really type. Hyphens are only
# split inside the no-space guard for exactly this reason.
for keep in ("work-life balance", "long-distance relationship advice", "burnout",
             "imposter syndrome", "e-book"):
    check(f"left alone {keep!r}", tg._clean(keep) == keep, tg._clean(keep))

print("\n3c. two passes, and neither can starve the other")
calls = []
def _two_pass_post(payload, timeout):
    prompt = payload["messages"][1]["content"]
    calls.append(prompt)
    if "SEPARATE words" in prompt:                       # the concept pass
        return {"choices": [{"message": {"content":
                json.dumps({"queries": ["imposter syndrome", "burnout", "deep work"]})}}]}
    # The needs pass OVER-DELIVERS: asked for 7, returns 12. This is what the real model
    # does, and before the per-pass cap it filled the whole quota so the concept pass
    # contributed nothing and every result came out long.
    return {"choices": [{"message": {"content": json.dumps({"queries":
            [f"how do I deal with problem number {i} at work" for i in range(12)]})}}]}

tg._post = _two_pass_post
out = tg.generate(themes, n=10)
check("two passes issued", len(calls) == 2, len(calls))
check("one pass per style",
      sum("SEPARATE words" in c for c in calls) == 1 and
      sum("situation" in c for c in calls) == 1, calls and len(calls))
check("returns exactly n", len(out) == 10, len(out))
short = [c["text"] for c in out if len(c["text"].split()) <= 3]
check("concept pass survives an over-delivering needs pass", len(short) == 3, short)
check("needs pass capped at its share", len(out) - len(short) == 7, len(out) - len(short))

calls.clear()
tg.generate(themes, n=6, backstory="just promoted, anxious about managing people")
check("backstory mode uses a single pass (variants of ONE need)", len(calls) == 1, len(calls))
calls.clear()
tg.generate(themes, n=3)
check("tiny n uses a single pass (1/1 split gives neither style room)",
      len(calls) == 1, len(calls))

print("\n3d. junk the model emits is dropped")
def _junk_post(payload, timeout):
    return {"choices": [{"message": {"content": json.dumps({"queries":
            ["...", "-", "  ", "ok", "a real query about managing stress"]})}}]}
tg._post = _junk_post
out = tg.generate(themes, n=4)
texts = [c["text"] for c in out]
check("'...' dropped (passes the length check, has no letters)", "..." not in texts, texts)
check("punctuation-only dropped", "-" not in texts and "" not in texts, texts)
check("a real query survives", any("managing stress" in t for t in texts), texts)

print("\n4. an unreachable server raises rather than returning nothing")
def _refuse(payload, timeout):
    raise OSError("connection refused")
tg._post = _refuse
try:
    tg.generate(themes, n=5)
    check("unreachable server raises", False, "returned instead of raising")
except RuntimeError as e:
    # Silent failure here would have the UI report "0 topics generated" while the real
    # problem is a server that was never started — sending you to debug the prompt.
    check("unreachable server raises RuntimeError", True)
    check("error names the URL so it is actionable", tg.TOPICS_URL in str(e), str(e))

print("\n5. curation is recorded: origin, edits, discards, and qid reuse")
os.environ["JUDGMENTS_PATH"] = os.path.join(tempfile.mkdtemp(), "judgments.json")
sys.path.insert(0, os.path.join(REPO, "ui"))
try:
    import api  # noqa: E402
except Exception as e:                     # ibm_db / fastapi missing
    print(f"SKIP — cannot import ui/api.py ({type(e).__name__}: {e})")
    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)

api.create_set({"name": "gen_test"})
# A hand-typed topic already in the store; the generator later proposes the same text.
api.post_judgment({"query": "managing stress", "cid": 1, "label": "relevant",
                   "pool_size": 3, "set": "gen_test"})

res = api.add_topics("gen_test", {
    "accepted": [
        {"text": "burnout recovery", "theme": "Health & Wellness"},
        {"text": "how do I say no at work", "theme": "Business & Careers",
         "edited": True, "original_text": "saying no at work"},
        {"text": "managing stress", "theme": "Health & Wellness"},   # collides with human
    ],
    "discarded": [{"text": "a bad candidate", "theme": "x", "reason": "too vague"}],
})
check("two new topics added", len(res["added"]) == 2, res["added"])
check("colliding topic reused, not duplicated", len(res["reused"]) == 1, res["reused"])

store = json.load(open(os.environ["JUDGMENTS_PATH"]))
by_text = {e["text"]: e for e in store["queries"].values()}
check("plain generated topic marked llm", by_text["burnout recovery"]["origin"] == "llm")
edited = by_text["how do I say no at work"]
check("edited topic marked llm_edited", edited["origin"] == "llm_edited")
check("edited topic keeps the model's original wording",
      edited["origin_detail"].get("original_text") == "saying no at work")
check("provenance records model + prompt version",
      bool(edited["origin_detail"].get("model")) and
      bool(edited["origin_detail"].get("prompt_version")))
# The important one: a hand-typed topic must not be relabelled as machine-authored just
# because the generator happened to propose the same words. That would silently destroy
# the human-vs-LLM comparison the origin field exists to support.
check("hand-typed topic keeps human origin",
      by_text["managing stress"].get("origin", "human") == "human",
      by_text["managing stress"].get("origin"))

disc = store["sets"]["gen_test"].get("discarded") or []
check("discard recorded, with its reason",
      len(disc) == 1 and disc[0]["reason"] == "too vague", disc)
check("discards get no qid (qids are the qrels join key)",
      not any(e["text"] == "a bad candidate" for e in store["queries"].values()))
check("accepted-but-unjudged topics have pool_size 0 (exporter skips them)",
      by_text["burnout recovery"]["pool_size"] == 0)

import export_judgments as xj  # noqa: E402
check("manifest reports the origin mix",
      xj.origin_counts([("q1", {"origin": "llm"}), ("q2", {}), ("q3", {"origin": "llm"})])
      == {"human": 1, "llm": 2})

print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
