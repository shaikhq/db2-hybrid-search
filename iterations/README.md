# Iteration ledger

One folder per iteration, recording **what you changed**, **what the app did before**,
and **what it does after**. You write the intent; the before/after capture is automatic.

```bash
./scripts/iterate start "label tab keyboard nav" -s demo-run,evaluate-set
#   ... change code, write your intent in the generated iteration.md ...
./scripts/iterate end
./scripts/iterate report      # -> iterations/index.html, every iteration side by side
```

## What lands on disk

```
iterations/
  0001-label-tab-keyboard-nav/
    iteration.md      the human record: why, what changed, and the before→after table
    meta.json         the machine record: git SHAs, scenarios, diff summary
    before/  after/
      demo-run.png    what the screen looked like
      demo-run.txt    what the screen SAID — titles, scores, verdicts
      demo-run.webm   optional, with --video (gitignored)
    diff/
      demo-run.diff.png   red = changed pixels, everything else dimmed
      demo-run.txt.diff   unified diff of the text — readable in a terminal
```

**Read the `.txt.diff` first.** The PNG tells you *that* the screen changed; the text
diff tells you *what the app said differently* — a result that moved, a verdict that
flipped, an nDCG that dropped. That is the part worth reviewing, and it diffs in git
like code.

## The scenarios

`./scripts/iterate scenarios` lists them. Each iteration captures only the ones it
touches — pass `-s name,name`. Editing the Demo tab does not need the Architecture
diagram re-photographed.

Scenarios are declared in [`scenarios.json`](scenarios.json) with a deliberately tiny
step vocabulary (`click`, `fill`, `press`, `select`, `wait_for`, `wait_ms`, `hover`,
`eval`). Add one whenever you start iterating on a flow that is not covered yet — it is
about six lines.

Two kinds:

| `needs` | Runs against | Reproducible? |
|---|---|---|
| `offline` | frozen fixtures, no Db2 — a static server this tool starts itself | **Byte-identical** between runs |
| `live` | `./ui/run.sh --live` (Db2 + embedding server), via `--live` | No — results move with the corpus |

Offline captures are deterministic because `scripts/uicapture.py` seeds `Math.random`
(the Demo tab shuffles its chips), freezes `Date`, and disables animations and the text
caret. So **any red in an offline diff is a real change**, never render jitter.

Live scenarios are skipped with a one-line reason when no backend is up, the same way
the suites in `tests/` skip. Read their diffs as "what the engine said today", not as a
regression alarm.

## The tool picks the scenarios and the target

You don't have to remember whether a change needs live. Say what you're about to touch:

```bash
./scripts/iterate plan -t src/hybrid_search/core.py     # ask, without starting
./scripts/iterate start "fusion weights" -t src/hybrid_search/core.py
```

[`routing.json`](routing.json) maps files → scenarios → offline-or-live, and prints its
reasoning:

```
  src/hybrid_search/core.py
    -> search-hybrid, search-compare, demo-run   [live]  retrieval + fusion. Offline
       serves frozen results, so it would show your change as unchanged
  => capture search-hybrid, search-compare, demo-run  against LIVE
```

**`live` wins any tie.** If even one changed file is something the offline UI serves from
a frozen fixture, offline capture would report your change as "unchanged" — a false
negative, the one failure this tool must not produce. Override with `--offline` if you
disagree; it says so out loud when you do.

`iterate start` runs *before* you edit, so there is usually no diff to read — that is what
`-t/--touching` is for. With no `-t`, it routes from whatever is already uncommitted, and
falls back to capturing everything.

At `end`, the routing is re-run against what you **actually** changed, and warns if you
drifted:

```
WARNING: what you changed routes to LIVE, but the baseline was captured offline...
WARNING: files you changed also route to: evaluate-set, label-pool
         — not in this iteration's baseline, so they cannot be diffed.
```

It warns rather than blocks — you may have good reason — but it says it plainly, because
the alternative is a clean-looking diff that proves nothing.

## Capturing everything against the live app

`--live` only adds the scenarios *declared* `needs: live`. To route **every** scenario at
the real backend — including ones that would otherwise use frozen fixtures:

```bash
./ui/run.sh --live &                                  # must be up first
./scripts/iterate start "rerank weighting" -s demo-run --all-live
./scripts/iterate end                                 # inherits --all-live automatically
```

Use it when you are changing something that only exists live — real Db2 ranking, the
reranker, fusion weights — because frozen fixtures would hide the very thing you changed.

What you give up: **reproducibility**. Two live captures of unchanged code can differ
(ranking, timing, corpus). So on a live iteration the pixel diff is evidence, not a
verdict — the **text diff is the one to read**. Iterations record which target they used,
`iteration.md` states it, and the report tags it with a blue `live` pill.

`iterate end` inherits the target from `start`, and refuses to mix them: an offline
`before` diffed against a live `after` would light up every scenario red for reasons that
have nothing to do with your change. To switch an in-flight iteration over, redo the
baseline with `./scripts/iterate recapture <slug> --all-live`.

## Conventions

- **Entries are append-only.** Don't rewrite iteration 7 when you change your mind —
  write iteration 12 and note that it supersedes 7. The log is a history, not a
  snapshot. (Same reasoning as an ADR log.)
- **Capture `before` *before* you touch the code.** `iterate start` photographs the
  working tree as it stands at that moment. If you forget and change something first,
  stash it and run `./scripts/iterate recapture`.
- **A diff is a question, not a failure.** Most will be intentional. The one to look
  twice at is the scenario you *didn't* mean to touch.

## Requirements

Playwright and Pillow, both already in the repo's test extras:

```bash
pip install -e ".[test]" && python -m playwright install chromium
```

Everything skips cleanly with an install hint if they are missing. `--video` needs
nothing extra (Playwright bundles its own ffmpeg); stitching before/after into a single
side-by-side GIF would need a system `ffmpeg`, which is not installed here.
