# Demo + Search — QA report

Audiobook-corpus UI. Verdicts derive from ground truth; all checks re-runnable.

## How to run the gate
```bash
PYTHONPATH=src python3 tests/test_demo_view.py                          # A/B/C — pure logic, no Db2
PYTHONPATH=src DB2_HOST=local .venv/bin/python tests/test_demo_ui.py    # D/E/F — TestClient + static
.venv/bin/python tests/test_demo_e2e.py                                 # D — real headless chromium
```

## Result: **129 passed · 0 failed** (last run)
- `test_demo_view.py` — **83/83** (contract over 9 queries, outcome-translation, honesty)
- `test_demo_ui.py` — **26/26** (static a11y/responsive, TestClient smoke inc. `/api/search`, regression)
- `test_demo_e2e.py` — **20/20** (real browser)

Screenshots eyeballed: Demo (9 chips, Semantic labels, verdict contrast, scoreboard+matrix) and Search
(open-ended, 3 columns × top-3) on desktop + 380px mobile.

## Demo deck — 9 queries, 3 per type, from the golden set (verified live)
| # | query | type | keyword | semantic | hybrid |
|---|---|---|---|---|---|
| 1 | finances… behavior not smart [75] | semantic | ✗ wrong | ✓ | ✓ |
| 2 | teddy hamilton [97] | keyword | ✓ | ✗ wrong | ✓ |
| 3 | the goggins one [67] | keyword | ✓ | ✓ | ✓ |
| 4 | why we misjudge people we've just met [69] | semantic | ✗ wrong | ✓ | ✓ |
| 5 | jason fung… blood-sugar [61] | mixed | ✓ | ✓ | ✓ |
| 6 | say no… vital few [39] | semantic | ✗ wrong | ✓ | ✓ |
| 7 | cal newport… without burning out [91] | mixed | ✓ | ✓ | ✓ |
| 8 | pragmatic programmer [72] | keyword | ✓ | ✓ | ✓ |
| 9 | matthews… for women [20] | mixed | ✓ | ✓ | ✓ |

**Coverage: keyword found 6/9 (blanks on the 3 semantic queries), semantic 8/9 (blanks on "teddy hamilton"),
hybrid 9/9.** Both single-leg blind spots are present and hybrid covers both — verified from ground truth.

## Changes this round
1. **Demo → 9 queries** (3 keyword / 3 semantic / 3 mixed), sourced from the golden eval set; `demo_fixtures.json` rebuilt live.
2. **"Meaning" → "Semantic"** everywhere in the demo (chip type label, strategy panel, provenance/fusion note, intro) — consistent with the query-type labels on the other tabs.
3. **Search tab reworked → open-ended:** removed the eval-query deck and the strategy picker; type any query and see the **top 3 results from all three strategies** (Lexical / Vector / Hybrid) side by side. Needs the live backend (`./ui/run.sh --live`), since arbitrary queries hit Db2.

## A–F summary (unchanged structure)
- **A/B/C** — contract shape over all 9 view models; every verdict branch (found/wrong/nothing, boundary k vs k+1); purity + no-hardcoding; scoreboard tally == counted "found". ✅
- **D (real browser)** — no JS errors (only by-design `/api/*` offline-probe 404s); tab switch fully hides other pages; 9 chips; 3 panels; Simple↔Technical toggle; scoreboard increments; unknown query → placeholder; verdicts icon+text; **Search tab renders open-ended box, deck removed**. ✅
- **E Regression** — Golden-eval cards still render; existing endpoints 200; `/api/search` returns 3 strategies with result lists. ✅
- **F Responsive + a11y** — 3-col ≥640px, stacked <640px; ARIA/`aria-live`; focus-visible; `.sr-only`; verdicts icon+text. ✅

## Notes
- Frozen JSON (`demo_fixtures.json`, `fixtures.json`, `eval_set.json`) is rebuilt from the current corpus/knobs — re-run the `ui/build_*.py` scripts after any change.
- Assets are cache-busted (`?v=3`) — a hard refresh loads the latest CSS/JS.

## Human-review (taste)
1. Do the 9 scenarios read plainly for a mixed audience?
2. Does the "confidently wrong" moment feel wrong (finance → Total Money Makeover; teddy hamilton → Think and Grow Rich)?
3. Is the coverage matrix legible at a glance?
