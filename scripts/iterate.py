#!/usr/bin/env python3
"""Iteration ledger: what changed, what the app did before, what it does after.

One folder per iteration, under iterations/. You write two sentences of intent; the
before/after capture is automatic.

    ./scripts/iterate start "label tab keyboard nav" -s demo-run,evaluate-set
    ...code...
    ./scripts/iterate end
    ./scripts/iterate report          # -> iterations/index.html

    ./scripts/iterate list            # every iteration and its state
    ./scripts/iterate scenarios       # the catalogue you pick -s from
    ./scripts/iterate recapture       # redo `before` (you started, then changed your mind)

Entries are append-only, in the spirit of an ADR log: you don't rewrite iteration 7 when
you change your mind, you write iteration 12 and note that it supersedes 7.

Add --live to include scenarios that need ./ui/run.sh --live, and --video to record a
.webm per scenario (Playwright ships its own ffmpeg; .webm is gitignored by default).
"""
import argparse
import datetime
import difflib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ITERS = os.path.join(REPO, "iterations")

sys.path.insert(0, HERE)
import uicapture  # noqa: E402

# Zero on purpose. The first draft used 0.001 to absorb "antialiasing jitter", and it
# promptly hid a real change: recolouring one chip's 1px border moved 0.072% of the
# pixels and got reported as "unchanged". Repeat captures are byte-identical (offline
# mode serves frozen fixtures, and uicapture seeds Math.random, freezes Date and kills
# animations), so there is no jitter to absorb — a floor only buys false negatives.
# Subtle changes are surfaced by their magnitude instead, via SUBTLE below.
NOISE_FLOOR = 0.0

# Per-pixel channel-sum threshold. This, not the floor above, is what ignores genuine
# antialiasing: a resampled glyph edge moves a few levels, a recolour moves tens.
PIXEL_DELTA = 24

# Changes smaller than this get an explicit "subtle" tag, so a 1px border tweak reads
# differently from a relaid-out panel without either being suppressed.
SUBTLE = 0.002


def sh(*args):
    try:
        return subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return ""


def git_state():
    return {
        "sha": sh("git", "rev-parse", "--short", "HEAD"),
        "branch": sh("git", "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(sh("git", "status", "--porcelain")),
    }


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "iteration"


def iter_dirs():
    if not os.path.isdir(ITERS):
        return []
    return sorted(d for d in os.listdir(ITERS)
                  if re.match(r"^\d{4}-", d) and os.path.isdir(os.path.join(ITERS, d)))


def read_meta(d):
    p = os.path.join(ITERS, d, "meta.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def write_meta(d, meta):
    with open(os.path.join(ITERS, d, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


def next_number():
    ds = iter_dirs()
    return (max(int(d[:4]) for d in ds) + 1) if ds else 1


def latest_open():
    """The most recent iteration that has a `before` but no `after`."""
    for d in reversed(iter_dirs()):
        m = read_meta(d)
        if m and not m.get("ended"):
            return d
    return None


def resolve(slug_or_none):
    if slug_or_none:
        matches = [d for d in iter_dirs() if d == slug_or_none or d[5:] == slug_or_none
                   or d.startswith(slug_or_none)]
        if not matches:
            raise SystemExit(f"no iteration matching {slug_or_none!r}")
        return matches[-1]
    d = latest_open()
    if d:
        return d
    # Fall back to the newest iteration even though it is closed, so `end --force` and
    # `recapture --force` can reach it. The caller's own already-ended check decides
    # whether to proceed, and its message names --force.
    ds = iter_dirs()
    if not ds:
        raise SystemExit("no iterations yet — run `iterate start \"...\"` first")
    return ds[-1]


# ------------------------------------------------------------------- routing / decision

ROUTING = os.path.join(ITERS, "routing.json")


def load_routing(path=ROUTING):
    with open(path) as f:
        return json.load(f)


def changed_files(since=None):
    """Repo-relative paths touched: uncommitted work, plus commits since `since`."""
    import fnmatch  # noqa: F401  (used by decide)
    paths = set()
    for line in sh("git", "status", "--porcelain").splitlines():
        p = line[3:].strip()
        # Renames read "old -> new"; the new path is what a rule should match.
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        if p:
            paths.add(p.strip('"'))
    if since:
        for p in sh("git", "diff", "--name-only", since, "HEAD").splitlines():
            if p.strip():
                paths.add(p.strip())
    return sorted(paths)


def decide(paths, routing=None):
    """Map changed files -> {scenarios, target, reasons, unmatched}.

    `live` wins any tie on purpose: if even one changed file is something the offline UI
    serves from a frozen fixture, an offline capture would report your change as
    "unchanged". A false negative is the one failure this tool must not produce.
    """
    import fnmatch
    r = routing or load_routing()
    scens, reasons, matched = [], [], set()
    target = "offline"

    for rule in r["rules"]:
        hit = sorted({p for p in paths for pat in rule["match"]
                      if fnmatch.fnmatch(p, pat)})
        if not hit:
            continue
        matched.update(hit)
        for s in rule["scenarios"]:
            if s not in scens:
                scens.append(s)
        if rule["target"] == "live":
            target = "live"
        reasons.append({"files": hit, "target": rule["target"], "why": rule["why"],
                        "scenarios": rule["scenarios"]})

    # A scenario needing live can't run offline either — same escalation.
    _, by_name = uicapture.load_catalogue()
    if any(by_name.get(s, {}).get("needs") == "live" for s in scens):
        target = "live"

    return {"scenarios": scens, "target": target, "reasons": reasons,
            "unmatched": sorted(set(paths) - matched)}


def print_decision(d, paths):
    if not paths:
        print("  (no changed files to reason about)")
        return
    for r in d["reasons"]:
        files = ", ".join(r["files"][:4]) + (" …" if len(r["files"]) > 4 else "")
        print(f"  {files}")
        print(f"    -> {', '.join(r['scenarios']) or '(none)'}   [{r['target']}]  {r['why']}")
    if d["unmatched"]:
        u = ", ".join(d["unmatched"][:6]) + (" …" if len(d["unmatched"]) > 6 else "")
        print(f"  not routed: {u}")
    if d["scenarios"]:
        print(f"\n  => capture {', '.join(d['scenarios'])}  against {d['target'].upper()}")
    else:
        print("\n  => nothing routed; no UI-visible change detected")


# ---------------------------------------------------------------- image + text diffing

def diff_images(before, after, out):
    """Write a diff PNG (changed pixels in red over a dimmed base). Returns pct changed."""
    from PIL import Image
    import numpy as np

    a = Image.open(before).convert("RGB")
    b = Image.open(after).convert("RGB")

    # A layout change resizes the element, so the two images differ in size. Pad both to
    # the union box rather than rescaling — rescaling would blur every pixel and report
    # 100% changed, telling you nothing about WHERE it changed.
    if a.size != b.size:
        w, h = max(a.width, b.width), max(a.height, b.height)
        pa = Image.new("RGB", (w, h), (255, 255, 255)); pa.paste(a, (0, 0)); a = pa
        pb = Image.new("RGB", (w, h), (255, 255, 255)); pb.paste(b, (0, 0)); b = pb
        resized = True
    else:
        resized = False

    na, nb = np.asarray(a, dtype=np.int16), np.asarray(b, dtype=np.int16)
    delta = np.abs(na - nb).sum(axis=2)
    changed = delta > PIXEL_DELTA
    pct = float(changed.mean())

    base = np.asarray(b.convert("L").convert("RGB"), dtype=np.uint8).copy()
    base = (base * 0.35 + 255 * 0.65 * 0).astype(np.uint8)   # dim the unchanged backdrop
    base[changed] = [255, 40, 40]
    Image.fromarray(base).save(out)
    return pct, resized


def diff_texts(before, after, out, name):
    with open(before) as f:
        a = f.read().splitlines()
    with open(after) as f:
        b = f.read().splitlines()
    lines = list(difflib.unified_diff(a, b, fromfile=f"before/{name}.txt",
                                      tofile=f"after/{name}.txt", lineterm=""))
    if lines:
        with open(out, "w") as f:
            f.write("\n".join(lines) + "\n")
    return len(lines)


def build_diffs(d):
    """Diff before/ against after/. Returns a per-scenario summary list."""
    root = os.path.join(ITERS, d)
    bdir, adir, ddir = (os.path.join(root, x) for x in ("before", "after", "diff"))
    os.makedirs(ddir, exist_ok=True)

    names = sorted({f[:-4] for f in os.listdir(bdir) if f.endswith(".png")} |
                   {f[:-4] for f in os.listdir(adir) if f.endswith(".png")})
    rows = []
    for n in names:
        bp, ap = os.path.join(bdir, f"{n}.png"), os.path.join(adir, f"{n}.png")
        row = {"name": n}
        if not os.path.exists(bp):
            row["pixels"] = "new in after"
        elif not os.path.exists(ap):
            row["pixels"] = "gone in after"
        else:
            pct, resized = diff_images(bp, ap, os.path.join(ddir, f"{n}.diff.png"))
            row["pct"] = pct
            if pct <= NOISE_FLOOR:
                row["pixels"] = "unchanged"
            else:
                # Two decimals would print a 1px border tweak as "0.07%"; three keeps
                # small-but-real changes legible instead of rounding them to 0.00%.
                row["pixels"] = (f"{pct*100:.3f}% of pixels changed"
                                 + (" · subtle" if pct < SUBTLE else "")
                                 + (" · element resized" if resized else ""))
        bt, at = os.path.join(bdir, f"{n}.txt"), os.path.join(adir, f"{n}.txt")
        if os.path.exists(bt) and os.path.exists(at):
            n_lines = diff_texts(bt, at, os.path.join(ddir, f"{n}.txt.diff"), n)
            row["text"] = "unchanged" if not n_lines else f"{n_lines} diff lines"
        else:
            row["text"] = "—"
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------- commands

TEMPLATE = """# {num} — {title}

- **Started:** {started}
- **Branch:** `{branch}` at `{sha}`{dirty}
- **Scenarios captured:** {scens}
- **Captured against:** {target}

## Why

<!-- One or two sentences. What prompted this? What is wrong or missing today? -->

## What I changed

<!-- Fill in as you go. Files, behavior, anything a future you would want to know. -->

## Before → After

<!-- `iterate end` writes the table here. Don't edit below this line by hand. -->
"""

MARK = "<!-- `iterate end` writes the table here. Don't edit below this line by hand. -->"

# Stated on every iteration, because it decides how much a pixel diff is worth.
TARGET_NOTE = {
    "offline": "**offline** — frozen fixtures. Repeat captures are byte-identical, so "
               "any pixel change is real.",
    "live": "**live** — real Db2 + embedding server. Results move with the corpus and "
            "the ranking, so treat pixel diffs as *what the engine said today*, not as "
            "a regression. The text diff is the one to read.",
}


def cmd_start(a):
    scens = [s.strip() for s in a.scenarios.split(",")] if a.scenarios else None
    _, by_name = uicapture.load_catalogue()
    if scens:
        unknown = [s for s in scens if s not in by_name]
        if unknown:
            raise SystemExit(f"unknown scenario(s): {', '.join(unknown)}\n"
                             f"see: ./scripts/iterate scenarios")

    # Decide scenarios + target from the files in play, rather than making you remember
    # a flag. --touching states what you are ABOUT to change (the usual case: `start`
    # runs before the edit, so there is no diff to read yet); otherwise fall back to
    # whatever is already uncommitted.
    decision = None
    if a.touching:
        paths = [p.strip() for p in a.touching.split(",") if p.strip()]
        src = "--touching"
    else:
        paths = changed_files()
        src = "uncommitted changes"
    if paths:
        decision = decide(paths)
        print(f"routing from {src}:")
        print_decision(decision, paths)
        print()

    auto_live = False
    if decision and decision["scenarios"]:
        if not scens:
            scens = decision["scenarios"]
        auto_live = decision["target"] == "live"
    elif not scens:
        print("note: nothing to route from, so capturing every scenario. Narrow it with\n"
              "      -s, or say what you're about to touch with --touching <paths>.")

    # --offline is the override for "I know it says live, capture offline anyway".
    if a.offline:
        auto_live = False
        if decision and decision["target"] == "live":
            print("note: --offline overrides the live routing above. Frozen fixtures may\n"
                  "      show your change as 'unchanged'.\n")
    if auto_live and not a.all_live:
        a.all_live = True

    num = f"{next_number():04d}"
    slug = slugify(a.title)
    d = f"{num}-{slug}"
    root = os.path.join(ITERS, d)
    if os.path.exists(root):
        raise SystemExit(f"{d} already exists")
    os.makedirs(os.path.join(root, "before"))

    g = git_state()
    started = datetime.datetime.now().isoformat(timespec="seconds")

    print(f"iteration {d}\ncapturing BEFORE from the working tree as it stands now"
          + (" (against the LIVE backend):" if a.all_live else ":"))
    res = uicapture.capture(os.path.join(root, "before"), names=scens,
                            live=a.live, base_url=a.base_url, video=a.video,
                            all_live=a.all_live)
    captured = res["captured"]
    if not captured:
        import shutil
        shutil.rmtree(root)
        if a.all_live:
            print("\nNothing captured. This change routes to LIVE, and no backend is up.\n"
                  "  Start it:  ./ui/run.sh --live\n"
                  "  Then:      ./scripts/iterate " + " ".join(sys.argv[1:]) + "\n"
                  "  Or force frozen fixtures with --offline (your change may not show).")
        else:
            print("\nNothing captured — not creating the iteration. Fix the above and retry.")
        return 1

    write_meta(d, {"num": num, "slug": slug, "title": a.title, "started": started,
                   "scenarios": scens or [s["name"] for s in _sc()],
                   "captured_before": captured,
                   "skipped_before": res["skipped"], "start_git": g,
                   "live": bool(a.live), "all_live": bool(a.all_live),
                   "target": res.get("target", "offline"),
                   "base_url": a.base_url, "video": bool(a.video), "ended": None,
                   "decision": decision, "routed_from": paths})

    with open(os.path.join(root, "iteration.md"), "w") as f:
        f.write(TEMPLATE.format(
            num=num, title=a.title, started=started, branch=g["branch"], sha=g["sha"],
            dirty="  *(uncommitted changes present)*" if g["dirty"] else "",
            scens=", ".join(f"`{c}`" for c in captured),
            target=TARGET_NOTE[res.get("target", "offline")]))

    print(f"\nBefore captured. Now go change things.")
    print(f"Write your intent in  iterations/{d}/iteration.md")
    print(f"When you're done:     ./scripts/iterate end")
    return 0


def _sc():
    cat, _ = uicapture.load_catalogue()
    return cat["scenarios"]


def cmd_end(a):
    d = resolve(a.slug)
    root = os.path.join(ITERS, d)
    meta = read_meta(d)
    if meta.get("ended") and not a.force:
        raise SystemExit(f"{d} already ended ({meta['ended']}). Use --force to redo `after`.")

    scens = meta.get("captured_before") or None
    adir = os.path.join(root, "after")
    os.makedirs(adir, exist_ok=True)

    # The `after` must come from the same place as the `before`. An offline before against
    # a live after diffs frozen fixtures with real Db2 output: every scenario lights up
    # red and none of it is your change. Inherit the target instead of letting the flag
    # silently differ between the two halves.
    all_live = a.all_live or meta.get("all_live", False)
    if a.all_live and not meta.get("all_live") and not a.force:
        raise SystemExit(
            f"{d} captured its `before` offline; --all-live here would diff frozen "
            f"fixtures against live Db2 and every scenario would show as changed.\n"
            f"  Either drop --all-live, or redo the before:  "
            f"./scripts/iterate recapture {d} --all-live")

    # What you ACTUALLY touched, versus what the target was chosen for at `start`. This is
    # the case the plan can't anticipate: you set out to restyle a chip and ended up in
    # core.py. Warn rather than block — you may have good reason — but say it plainly,
    # because the alternative is a clean-looking diff that proves nothing.
    actual = changed_files(since=meta.get("start_git", {}).get("sha"))
    if actual:
        now = decide(actual)
        missed = [s for s in now["scenarios"] if s not in (meta.get("captured_before") or [])]
        if now["target"] == "live" and meta.get("target") != "live":
            print("WARNING: what you changed routes to LIVE, but the baseline was captured\n"
                  "         offline against frozen fixtures — which may show your change as\n"
                  "         'unchanged'. To redo it properly:\n"
                  f"           ./scripts/iterate recapture {d} --all-live   (needs ./ui/run.sh --live)\n")
        if missed:
            print(f"WARNING: files you changed also route to: {', '.join(missed)}\n"
                  f"         — not in this iteration's baseline, so they cannot be diffed.\n")

    print(f"iteration {d}\ncapturing AFTER"
          + (" (against the LIVE backend):" if all_live else ":"))
    res = uicapture.capture(adir, names=scens,
                            live=a.live or meta.get("live"),
                            base_url=a.base_url or meta.get("base_url"),
                            video=a.video or meta.get("video"),
                            all_live=all_live)
    if not res["captured"]:
        print("\nNothing captured — leaving the iteration open.")
        return 1

    print("\ndiffing:")
    rows = build_diffs(d)
    for r in rows:
        print(f"  {r['name']:<18} pixels: {r.get('pixels','—'):<34} text: {r['text']}")

    g = git_state()
    ended = datetime.datetime.now().isoformat(timespec="seconds")
    meta.update({"ended": ended, "end_git": g, "captured_after": res["captured"],
                 "skipped_after": res["skipped"], "diff": rows})
    write_meta(d, meta)

    # Append the table to iteration.md, replacing any previous one (--force reruns).
    md_path = os.path.join(root, "iteration.md")
    with open(md_path) as f:
        body = f.read()
    head = body.split(MARK)[0] + MARK
    table = ["", "",
             f"- **Ended:** {ended}",
             f"- **Branch:** `{g['branch']}` at `{g['sha']}`"
             + ("  *(uncommitted changes present)*" if g["dirty"] else ""),
             "",
             "| Scenario | Screen | Text (what it said) | Files |",
             "|---|---|---|---|"]
    for r in rows:
        n = r["name"]
        links = f"[before](before/{n}.png) · [after](after/{n}.png)"
        if os.path.exists(os.path.join(root, "diff", f"{n}.diff.png")):
            links += f" · [diff](diff/{n}.diff.png)"
        if os.path.exists(os.path.join(root, "diff", f"{n}.txt.diff")):
            links += f" · [text diff](diff/{n}.txt.diff)"
        table.append(f"| `{n}` | {r.get('pixels','—')} | {r['text']} | {links} |")
    table += ["", "_Diff images: red = changed pixels. Offline captures are "
                  "byte-reproducible, so any red at all is a real change — `subtle` "
                  "just means small (a border, a shifted label), not negligible._", ""]
    with open(md_path, "w") as f:
        f.write(head + "\n".join(table))

    print(f"\nDone. Read it:  iterations/{d}/iteration.md")
    print(f"Rebuild the index:  ./scripts/iterate report")
    return 0


def cmd_recapture(a):
    d = resolve(a.slug)
    meta = read_meta(d)
    if meta.get("ended") and not a.force:
        raise SystemExit(f"{d} is closed. --force to recapture its `before` anyway.")
    bdir = os.path.join(ITERS, d, "before")
    print(f"iteration {d}\nre-capturing BEFORE (overwrites the previous one):")
    all_live = a.all_live or meta.get("all_live", False)
    res = uicapture.capture(bdir, names=meta.get("captured_before") or None,
                            live=a.live or meta.get("live"),
                            base_url=a.base_url or meta.get("base_url"),
                            video=a.video or meta.get("video"), all_live=all_live)
    meta["captured_before"] = res["captured"]
    meta["all_live"] = bool(all_live)
    meta["target"] = res.get("target", "offline")
    meta["start_git"] = git_state()
    write_meta(d, meta)
    return 0


def cmd_list(a):
    ds = iter_dirs()
    if not ds:
        print("No iterations yet.  ./scripts/iterate start \"my first change\"")
        return 0
    for d in ds:
        m = read_meta(d) or {}
        state = "open  " if not m.get("ended") else "closed"
        changed = ""
        if m.get("diff"):
            n = sum(1 for r in m["diff"]
                    if r.get("pixels") not in (None, "unchanged", "—"))
            changed = f"  ({n}/{len(m['diff'])} scenario(s) changed)"
        print(f"  [{state}] {d}{changed}")
        print(f"           {m.get('title','')}  ·  {m.get('started','')[:16]}")
    return 0


def cmd_plan(a):
    """Ask what an iteration over these files would capture, without starting one."""
    if a.touching:
        paths = [p.strip() for p in a.touching.split(",") if p.strip()]
        print(f"routing from --touching ({len(paths)} path(s)):")
    else:
        paths = changed_files()
        print(f"routing from uncommitted changes ({len(paths)} path(s)):")
    d = decide(paths)
    print_decision(d, paths)
    if d["target"] == "live":
        print("\n  live capture needs ./ui/run.sh --live running first.")
    return 0


def cmd_scenarios(a):
    for s in _sc():
        print(f"  {s['name']:<18} [{s.get('needs','offline'):<7}] {s.get('about','')}")
    return 0


def cmd_report(a):
    ds = iter_dirs()
    parts = [HTML_HEAD]
    if not ds:
        parts.append("<p class='empty'>No iterations yet.</p>")
    for d in reversed(ds):
        m = read_meta(d) or {}
        state = "open" if not m.get("ended") else "closed"
        tgt = m.get("target", "offline")
        parts.append(f"<section class='it'><h2>{d} <span class='pill {state}'>{state}</span>"
                     f"<span class='pill tgt-{tgt}'>{tgt}</span></h2>")
        parts.append(f"<p class='ttl'>{_esc(m.get('title',''))}</p>")
        gs, ge = m.get("start_git", {}), m.get("end_git", {})
        parts.append(f"<p class='meta'>{m.get('started','')[:16]}"
                     + (f" → {m.get('ended','')[:16]}" if m.get("ended") else "")
                     + f" · <code>{gs.get('branch','')}</code> "
                     + f"<code>{gs.get('sha','')}</code>"
                     + (f" → <code>{ge.get('sha','')}</code>" if ge.get("sha") else "")
                     + f" · <a href='{d}/iteration.md'>iteration.md</a></p>")
        for r in (m.get("diff") or []):
            n = r["name"]
            parts.append(f"<h3>{n} <small>{_esc(str(r.get('pixels','')))} · text: "
                         f"{_esc(str(r.get('text','')))}</small></h3>")
            parts.append("<div class='row'>")
            for label, path in (("before", f"{d}/before/{n}.png"),
                                ("after", f"{d}/after/{n}.png"),
                                ("diff", f"{d}/diff/{n}.diff.png")):
                if os.path.exists(os.path.join(ITERS, path)):
                    parts.append(f"<figure><figcaption>{label}</figcaption>"
                                 f"<a href='{path}'><img src='{path}' loading='lazy'></a></figure>")
            parts.append("</div>")
            td = os.path.join(ITERS, d, "diff", f"{n}.txt.diff")
            if os.path.exists(td):
                with open(td) as f:
                    parts.append(f"<pre class='td'>{_esc(f.read())}</pre>")
        if not m.get("ended"):
            parts.append("<p class='meta'>Still open — no <code>after</code> yet.</p>")
        parts.append("</section>")
    parts.append("</body>")
    out = os.path.join(ITERS, "index.html")
    with open(out, "w") as f:
        f.write("\n".join(parts))
    print(f"wrote {out}  ({len(ds)} iteration(s))")
    return 0


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


HTML_HEAD = """<!doctype html><meta charset=utf-8><title>Iteration ledger</title>
<style>
 body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      margin:0 auto;padding:32px;max-width:1400px;color:#1a1a1a;background:#fafafa}
 h1{margin:0 0 24px}
 .it{background:#fff;border:1px solid #e4e4e7;border-radius:10px;padding:20px 24px;
     margin-bottom:24px}
 .it h2{margin:0 0 4px;font-size:18px}
 .ttl{margin:0 0 6px;font-size:16px;color:#27272a}
 .meta{margin:0 0 14px;color:#71717a;font-size:13px}
 .pill{font-size:11px;padding:2px 8px;border-radius:99px;vertical-align:middle;
       text-transform:uppercase;letter-spacing:.04em}
 .pill.open{background:#fef3c7;color:#92400e}
 .pill.closed{background:#dcfce7;color:#166534}
 .pill.tgt-live{background:#dbeafe;color:#1e40af;margin-left:6px}
 .pill.tgt-offline{background:#f4f4f5;color:#52525b;margin-left:6px}
 h3{margin:18px 0 8px;font-size:14px;font-weight:600}
 h3 small{font-weight:400;color:#71717a;margin-left:8px}
 .row{display:flex;gap:12px;flex-wrap:wrap;overflow-x:auto}
 figure{margin:0;flex:1 1 300px;min-width:260px}
 figcaption{font-size:12px;color:#71717a;margin-bottom:4px}
 img{width:100%;border:1px solid #e4e4e7;border-radius:6px;display:block;background:#fff}
 .td{background:#18181b;color:#e4e4e7;padding:12px 14px;border-radius:6px;font-size:12px;
     overflow-x:auto;max-height:340px}
 .empty{color:#71717a}
 code{background:#f4f4f5;padding:1px 5px;border-radius:4px;font-size:12px}
 @media(prefers-color-scheme:dark){
   body{background:#0c0c0d;color:#e4e4e7}
   .it{background:#18181b;border-color:#27272a}
   .ttl{color:#e4e4e7} code{background:#27272a}
 }
</style>
<body><h1>Iteration ledger</h1>
"""


def main():
    ap = argparse.ArgumentParser(prog="iterate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_capture_flags(p):
        p.add_argument("--live", action="store_true",
                       help="include scenarios needing ./ui/run.sh --live")
        p.add_argument("--all-live", action="store_true",
                       help="capture EVERY scenario against the live backend "
                            "(implies --live); not reproducible — see iterations/README.md")
        p.add_argument("--base-url", default=None, help="live server URL")
        p.add_argument("--video", action="store_true", help="record a .webm per scenario")

    p = sub.add_parser("start", help="open an iteration and capture `before`")
    p.add_argument("title")
    p.add_argument("-s", "--scenarios", help="comma-separated (see: iterate scenarios). "
                                             "Omit to let --touching decide.")
    p.add_argument("-t", "--touching", help="comma-separated paths you are about to "
                                            "change; routes scenarios AND offline-vs-live")
    p.add_argument("--offline", action="store_true",
                   help="force frozen fixtures even when routing says live")
    add_capture_flags(p)
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("plan", help="show what would be captured, without starting")
    p.add_argument("-t", "--touching", help="comma-separated paths (default: uncommitted)")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("end", help="capture `after`, diff, write the table")
    p.add_argument("slug", nargs="?", help="default: the newest open iteration")
    p.add_argument("--force", action="store_true", help="redo `after` on a closed one")
    add_capture_flags(p)
    p.set_defaults(fn=cmd_end)

    p = sub.add_parser("recapture", help="redo `before` on an open iteration")
    p.add_argument("slug", nargs="?")
    p.add_argument("--force", action="store_true")
    add_capture_flags(p)
    p.set_defaults(fn=cmd_recapture)

    p = sub.add_parser("list", help="every iteration and its state")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("scenarios", help="the scenario catalogue")
    p.set_defaults(fn=cmd_scenarios)

    p = sub.add_parser("report", help="build iterations/index.html")
    p.set_defaults(fn=cmd_report)

    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
