"""
hybrid_search/topicgen.py — LLM-assisted TOPIC generation for building test collections.

An AUTHORING tool, not part of the retrieval path. It proposes candidate queries for a
human to edit, discard, and then judge by hand. Nothing it produces enters a test set
without passing through a person.

THE ONE DESIGN RULE, and the reason this module is safe to use at all:

    Generation never sees document text, and never runs retrieval.

docs/eval-framework-insights.md establishes why, from this repo's own data. Generating a
query FROM a source document makes the query inherit that document's vocabulary and
produces overwhelmingly known-item queries — 103 of 118 entries in golden_set. And
"consistency filtering" (keep the query only if the current system retrieves the source
document) selects for queries the system already answers, so the resulting set can only
ever agree with the retriever that built it. That is exactly why golden_set says hybrid
wins while both human-judged sets say vector does.

So this module conditions ONLY on collection-level themes — the `genres` and `pillar`
columns, never `chunk_text`/`title`/`description` — and never calls core.lexical/vector/
hybrid. No target document exists before the query, which is the setup Alaofi et al.
(SIGIR 2023) evaluated: LLM queries generated from information-need backstories reached
71.1% pool overlap with human-written queries at pool depth 100.

Known limitation, mitigated in the prompt rather than denied: synthetic queries run
LONGER and less varied than real ones (Rahmani et al., CIKM 2025). LENGTH_GUIDANCE below
asks explicitly for a mix including terse 2-3 word queries. Human review of every
candidate is the other half of the mitigation, and is the whole point of the edit/discard
step in the UI.

Config (env / .env, read via core.setting):
  TOPICS_URL, TOPICS_MODEL, TOPICS_TIMEOUT, TOPICS_TEMP, TOPICS_TOP_P, TOPICS_MAX
"""
import json
import logging
import re
import urllib.error
import urllib.request

from . import core as h   # for setting() only — no retrieval function is imported

log = logging.getLogger("hybrid_search.topicgen")

TOPICS_URL     = h.setting("TOPICS_URL", "http://127.0.0.1:8088").rstrip("/")
TOPICS_MODEL   = h.setting("TOPICS_MODEL", "topics")
TOPICS_TIMEOUT = float(h.setting("TOPICS_TIMEOUT", "60.0"))
# Sampled, NOT greedy. The query-understanding server runs --temp 0 --top-k 1 because a
# routing gate must be reproducible; here the entire value is variety, and greedy decoding
# returns near-duplicate phrasings of the same handful of needs.
TOPICS_TEMP    = float(h.setting("TOPICS_TEMP", "0.9"))
TOPICS_TOP_P   = float(h.setting("TOPICS_TOP_P", "0.95"))
TOPICS_MAX     = int(h.setting("TOPICS_MAX", "40"))     # per request, a sanity cap

PROMPT_VERSION = "topics-v1"

# TWO PASSES, ONE STYLE EACH — the mitigation for the documented "synthetic queries are
# longer than real ones" bias, arrived at by testing against the real 3B model.
#
# Asking one call for a MIX does not work. Qwen2.5-3B applies whichever length instruction
# is most concrete to EVERY item, so the distribution collapses to one end:
#   "a third should be terse fragments"      -> 12/12 single words ("grow", "time", "self")
#   "exactly 3 of 10 must be two words"      -> 10/10 two-word topic labels
#   "at least half must be 6+ words"         -> 10/10 polite full sentences
# Few-shot examples are worse, not better: same-domain examples got copied verbatim
# (one example produced "imposter syndrome" in 4 of 10 outputs), and cross-domain ones
# were copied wholesale too ("cast iron", "knife sharpening" from a cooking example).
#
# So the caller enforces the distribution instead of hoping the model holds it: one call
# for situations/questions, one for short concept names, merged at the ratio below. Each
# call gets a single unambiguous instruction, which is the thing the model does reliably.
SHORT_SHARE = float(h.setting("TOPICS_SHORT_SHARE", "0.3"))

_COMMON_RULES = (
    "- Every query must describe a real need, or name a specific concept. Never answer "
    'with a single common word such as "grow", "time" or "self" — nobody searches that.\n'
    "- Use a DIFFERENT subject area for each one, and do not repeat a concept.\n"
)
NEEDS_RULES = (
    "Rules:\n" + _COMMON_RULES +
    "- Write each as a question or a plain phrase describing someone's situation.\n"
    "- Do not make them all polite, well-formed sentences; real searches are often blunt "
    "or clumsy."
)
CONCEPT_RULES = (
    "Rules:\n" + _COMMON_RULES +
    "- Write each as two or three SEPARATE words with normal spaces between them. Lower "
    "case. No verb, no question mark, no punctuation, no CamelCase, no '&'.\n"
    "- Name a specific idea INSIDE a subject area — do NOT just repeat the subject-area "
    "names I listed back to me."
)

SYSTEM = (
    "You write realistic search queries for testing a search engine. You are given the "
    "subject areas a library covers. You invent what a PERSON might type when looking for "
    "something in it. You never describe or name specific items in the library — you have "
    "not seen them, and you must not guess at titles or authors."
)


def _unrun(s):
    """Repair a run-together token: 'small_business_taxes' -> 'small business taxes'.

    The concept pass is told to write separate words and mostly does — but not reliably.
    Across repeated live runs the same prompt produced clean phrases once and
    'ProductivityStrategies' / 'Education&Learning' / 'career_mistakes_growth_fix' the
    next time. Prompting cannot guarantee it, so repair it here.

    Deliberately narrow: only fires on a string with NO spaces that is longer than 12
    characters. A genuine short query ('burnout', 'imposter syndrome') is never touched,
    and neither is anything already spaced.
    """
    # Underscores are never natural in a typed query, and the model mixes them into
    # otherwise-spaced strings too ("how_to_start_a_business small_business"), so this
    # runs unconditionally rather than only on the no-space case.
    s = " ".join(re.sub(r"_+", " ", s).split())
    if " " in s or len(s) <= 12:
        return s
    # Hyphens are split ONLY here, inside the no-space guard. Blanket-replacing them
    # would wreck legitimate queries — "work-life balance", "long-distance relationship"
    # — but "how-to-build-a-successful-business" as a single token is never what someone
    # typed, and the model produces exactly that.
    s = re.sub(r"-+", " ", s)
    s = re.sub(r"\s*&\s*", " ", s)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)      # CamelCase boundary
    return " ".join(s.split())


def _clean(text):
    """One candidate query: collapse whitespace, strip list numbering and stray quotes."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    s = re.sub(r'^\s*(?:[-*•]|\d+[.)])\s*', "", s)     # "1. ", "- ", "• "
    return _unrun(s.strip().strip('"“”').strip())


def collection_profile(rows, top=14):
    """Collection-level themes from corpus metadata.

    Reads ONLY the `genres` and `pillar` columns. It must never touch chunk_text, title,
    authors or description — that is the boundary this whole module rests on, and
    tests/test_topicgen.py asserts it by passing rows whose text fields would poison the
    output if they were read.

    `genres` is pipe-separated within a comma-free cell ("Business & Careers|Relationships"),
    so split on "|" to recover individual genres rather than 94 near-unique combinations.
    """
    counts = {}
    for r in rows:
        for field, sep in (("genres", "|"), ("pillar", ",")):
            for part in str(r.get(field) or "").split(sep):
                part = part.strip()
                if part and part.lower() != "other":       # 'other' is 61/92 here: no signal
                    counts[part] = counts.get(part, 0) + 1
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]


def build_prompt(themes, n, backstory=None, style=None):
    """The user-turn prompt. Themes only — never document text.

    `style` is NEEDS_RULES or CONCEPT_RULES; see the comment above them for why the two
    are issued as separate calls rather than as one mixed instruction.
    """
    style = NEEDS_RULES if style is None else style
    themes_line = ", ".join(themes) if themes else "general non-fiction"
    if backstory:
        need = (f"Here is one person's situation:\n\n  {backstory.strip()}\n\n"
                f"Write {n} DIFFERENT queries that this same person might type while "
                f"looking for something to help. Different wordings and different angles "
                f"on the same underlying need.")
    else:
        need = (f"The library covers these subject areas: {themes_line}.\n\n"
                f"Write {n} different queries that different people might type when "
                f"searching it. Spread them across the subject areas and across kinds of "
                f"need — some looking for a specific known thing, most just describing a "
                f"problem they want help with.")
    return (f"{need}\n\n{style}\n\n"
            f'Reply as JSON only: {{"queries": ["...", "..."]}}')


def _post(payload, timeout):
    req = urllib.request.Request(
        f"{TOPICS_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse(content):
    """Pull the query list out of the model's reply.

    The server is started with a JSON grammar so `content` should already be
    {"queries": [...]}, but the parse stays tolerant: a grammar-less server (or a future
    model swap) should degrade to 'still works' rather than 'silently returns nothing'.
    """
    content = (content or "").strip()
    try:
        obj = json.loads(content)
        if isinstance(obj, dict) and isinstance(obj.get("queries"), list):
            return obj["queries"]
        if isinstance(obj, list):
            return obj
    except (ValueError, TypeError):
        pass
    m = re.search(r'"queries"\s*:\s*\[(.*?)\]', content, re.S)   # JSON wrapped in prose
    if m:
        return re.findall(r'"([^"]+)"', m.group(1))
    return [ln for ln in content.splitlines() if ln.strip()]      # last resort: lines


def _one_pass(themes, n, backstory, style, timeout):
    """One call to the model. Returns raw strings, uncleaned and undeduped."""
    payload = {
        "model": TOPICS_MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user",
                      "content": build_prompt(themes, n, backstory, style)}],
        "temperature": TOPICS_TEMP,
        "top_p": TOPICS_TOP_P,
        "max_tokens": 64 * n + 128,
    }
    try:
        body = _post(payload, timeout or TOPICS_TIMEOUT)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise RuntimeError(f"topic-generation server unreachable at {TOPICS_URL}: {e}")
    except Exception as e:                                   # malformed HTTP/JSON
        raise RuntimeError(f"topic-generation server error: {e}")
    try:
        return _parse(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("topic-generation server returned an unexpected response shape")


def generate(themes, n=10, backstory=None, timeout=None):
    """Generate up to `n` candidate queries. Returns [{"text", "theme"}].

    Two calls when there is room for both styles (see NEEDS_RULES / CONCEPT_RULES): the
    length distribution is enforced here rather than requested from the model, because
    the model cannot hold a mixed distribution within one response.

    Raises RuntimeError when the server is unreachable or returns nothing usable —
    unlike rerank.py, there is no silent fallback here. Reranking degrading to fusion
    order is invisible and fine; topic generation degrading to an empty list while the
    UI says "generated" would have the assessor believe the model produced nothing when
    the server was simply down.
    """
    n = max(1, min(int(n), TOPICS_MAX))
    # Backstory mode asks for variants of ONE stated need, so splitting it by style would
    # just be two half-sized takes on the same thing. Small n likewise: a 2-item request
    # split 1/1 gives the model no room to vary either style.
    if backstory or n < 4:
        passes = [(n, NEEDS_RULES)]
    else:
        n_short = max(1, round(n * SHORT_SHARE))
        passes = [(n - n_short, NEEDS_RULES), (n_short, CONCEPT_RULES)]

    seen, out = set(), []
    theme_label = "backstory" if backstory else (", ".join(themes[:3]) if themes else "")
    for count, style in passes:
        taken = 0
        for raw in _one_pass(themes, count, backstory, style, timeout):
            # Cap each pass at what it was asked for. The model over-delivers (asked 7,
            # returned 10), and without this the first pass fills the whole quota and the
            # concept pass never runs — silently reverting to all-long output.
            if taken >= count:
                break
            text = _clean(raw)
            # 3 chars filters the model's occasional stray token; 200 filters a runaway
            # paragraph, which is not a query anyone would type.
            if not (3 <= len(text) <= 200):
                continue
            # Must contain a letter: the model emits a bare "..." often enough to matter,
            # and it passes the length check.
            if not re.search(r"[A-Za-z]", text):
                continue
            key = " ".join(text.split()).casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append({"text": text, "theme": theme_label})
            taken += 1

    if not out:
        raise RuntimeError("topic-generation produced no usable queries")
    log.info("topicgen: %d candidates (asked %d, %d pass(es))", len(out), n, len(passes))
    return out[:n]


def origin_detail(theme=None):
    """Provenance stamped onto an accepted topic. `generated_at` is filled by the caller
    (ui/api.py), which owns the clock — keeping this module free of time so its output is
    reproducible under test."""
    return {"model": TOPICS_MODEL, "prompt_version": PROMPT_VERSION, "theme": theme or ""}
