#!/usr/bin/env python3
"""Drive the UI with Playwright and freeze what it does: a PNG per scenario, plus a
plain-text dump of what the panel actually said.

The text dump is the half that matters in review. A PNG diff tells you THAT the page
changed; `search-hybrid.txt` diffs in git as words — result titles, scores, verdicts —
so you can read the behavior change without opening an image viewer.

Used by scripts/iterate.py (`iterate start` / `iterate end`). Runnable on its own:

    .venv/bin/python scripts/uicapture.py OUTDIR                 # all offline scenarios
    .venv/bin/python scripts/uicapture.py OUTDIR -s demo-run     # just these
    .venv/bin/python scripts/uicapture.py OUTDIR --live          # include live scenarios
    .venv/bin/python scripts/uicapture.py OUTDIR --video         # also record .webm

Offline scenarios are served here, from ui/static, on an ephemeral port — nothing to
start first. Live scenarios need `./ui/run.sh --live` already running (default
http://127.0.0.1:8000, override with --base-url); they are skipped with a one-line
reason when it is not reachable, matching the convention in tests/.
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
STATIC = os.path.join(REPO, "ui", "static")
CATALOGUE = os.path.join(REPO, "iterations", "scenarios.json")

INSTALL_HINT = '  pip install -e ".[test]" && python -m playwright install chromium'

# Everything that would make two captures of an unchanged page differ. Without these the
# baseline is noise and every diff is a false positive.
#
# ui/static/demo.js:55 shuffles the example chips with Math.random(), so a bare capture
# reorders the sidebar on every run. Seed it with a fixed LCG instead of stubbing it to a
# constant — a constant makes Fisher-Yates degenerate and hides real ordering bugs.
DETERMINISM_JS = """
(() => {
  let seed = 20260804;
  Math.random = () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; };
  // Freeze the clock: anything rendering a timestamp would otherwise diff every run.
  const FIXED = 1780531200000;  // 2026-06-04T08:00:00Z
  const _Date = Date;
  Date.now = () => FIXED;
  window.Date = class extends _Date {
    constructor(...a) { super(...(a.length ? a : [FIXED])); }
    static now() { return FIXED; }
  };
})();
"""

# Animations mid-flight are the other flake source: the same page photographed 20ms apart
# gives two different images. Also hide the text caret, which blinks.
STILL_CSS = """
*, *::before, *::after {
  animation-duration: 0s !important; animation-delay: 0s !important;
  transition-duration: 0s !important; transition-delay: 0s !important;
  caret-color: transparent !important;
}
"""


def load_catalogue(path=CATALOGUE):
    with open(path) as f:
        cat = json.load(f)
    return cat, {s["name"]: s for s in cat["scenarios"]}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def normalize_text(raw):
    """Make the text dump diff cleanly: strip trailing spaces, collapse blank runs.

    Kept deliberately dumb — no number rounding, no masking. If a score moves from 0.812
    to 0.809 that IS the behavior change you are trying to see.
    """
    lines = [ln.rstrip() for ln in (raw or "").splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    return "\n".join(out).strip() + "\n"


def run_steps(page, steps):
    for step in steps:
        if "click" in step:
            page.click(step["click"], timeout=10000)
        elif "fill" in step:
            page.fill(step["fill"], step.get("text", ""), timeout=10000)
        elif "press" in step:
            target = step.get("on")
            if target:
                page.press(target, step["press"], timeout=10000)
            else:
                page.keyboard.press(step["press"])
        elif "select" in step:
            page.select_option(step["select"], step.get("value"), timeout=10000)
            # select_option fires `change`, but the handler may re-render async.
            page.wait_for_timeout(150)
        elif "hover" in step:
            page.hover(step["hover"], timeout=10000)
        elif "wait_for" in step:
            page.wait_for_selector(step["wait_for"], timeout=15000)
        elif "wait_ms" in step:
            page.wait_for_timeout(step["wait_ms"])
        elif "eval" in step:
            page.evaluate(step["eval"])
        else:
            raise ValueError(f"unknown step: {step!r}")


def capture_one(browser, base_url, scen, outdir, viewport, video=False):
    """One scenario -> one PNG + one .txt (+ optional .webm). Returns a result dict."""
    name = scen["name"]
    ctx_args = {"viewport": viewport, "device_scale_factor": 1,
                "reduced_motion": "reduce"}
    if video:
        ctx_args["record_video_dir"] = outdir
        ctx_args["record_video_size"] = viewport
    ctx = browser.new_context(**ctx_args)
    ctx.add_init_script(DETERMINISM_JS)
    page = ctx.new_page()

    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text)
            if (m.type == "error" and "Failed to load resource" not in m.text) else None)

    try:
        page.goto(base_url, wait_until="networkidle", timeout=30000)
        page.add_style_tag(content=STILL_CSS)
        run_steps(page, scen.get("steps", []))
        # Let fonts settle and any in-flight paint finish before photographing.
        page.wait_for_timeout(250)

        cap = scen.get("capture", {})
        shot_sel = cap.get("shot", "page")
        text_sel = cap.get("text", "page")

        png = os.path.join(outdir, f"{name}.png")
        if shot_sel == "page":
            page.screenshot(path=png, full_page=True)
        else:
            page.locator(shot_sel).first.screenshot(path=png)

        raw = (page.inner_text("body") if text_sel == "page"
               else page.locator(text_sel).first.inner_text())
        with open(os.path.join(outdir, f"{name}.txt"), "w") as f:
            f.write(normalize_text(raw))

        vid_path = None
        if video:
            vid_path = page.video.path()
        page.close()
        ctx.close()
        # The video is only flushed to disk on context close, hence the rename after.
        if vid_path and os.path.exists(vid_path):
            os.replace(vid_path, os.path.join(outdir, f"{name}.webm"))

        return {"name": name, "status": "ok", "console_errors": console_errors}
    except Exception as e:
        try:
            page.close(); ctx.close()
        except Exception:
            pass
        return {"name": name, "status": "error", "detail": f"{type(e).__name__}: {e}"}


def capture(outdir, names=None, live=False, base_url=None, video=False,
            catalogue=CATALOGUE, quiet=False, all_live=False):
    """Capture `names` (default: every scenario the current mode can reach) into outdir.

    Three targeting modes:
      (default)   offline scenarios -> a static server started here; live ones skipped.
      live=True   as above, plus `needs: live` scenarios against the running backend.
      all_live    EVERY scenario against the running backend, including ones that could
                  have run offline. Use when you are changing behavior that only exists
                  live (real Db2 ranking, the reranker) and frozen fixtures would hide
                  the very thing you changed. Costs reproducibility — see the note in
                  iterations/README.md.

    Returns {"captured": [...], "skipped": [...], "errors": [...], "target": ...}.
    """
    cat, by_name = load_catalogue(catalogue)
    viewport = cat.get("viewport", {"width": 1280, "height": 900})

    if names:
        unknown = [n for n in names if n not in by_name]
        if unknown:
            raise SystemExit(f"unknown scenario(s): {', '.join(unknown)}\n"
                             f"known: {', '.join(by_name)}")
        wanted = [by_name[n] for n in names]
    else:
        wanted = list(cat["scenarios"])

    os.makedirs(outdir, exist_ok=True)
    say = (lambda *a: None) if quiet else print

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        say(f"SKIP — playwright not installed. Install the test extras:\n{INSTALL_HINT}")
        return {"captured": [], "skipped": [s["name"] for s in wanted], "errors": []}

    if all_live:
        live = True                       # --all-live implies --live; asking for both is
                                          # the same request stated twice.
    offline = [] if all_live else [s for s in wanted if s.get("needs", "offline") != "live"]
    live_scens = wanted if all_live else [s for s in wanted if s.get("needs") == "live"]

    result = {"captured": [], "skipped": [], "errors": [],
              "target": "live" if all_live else "offline"}

    # Is a live server actually up? Only ask when something needs it.
    live_url = base_url or "http://127.0.0.1:8000"
    live_ok = False
    if live_scens and live:
        try:
            live_ok = urllib.request.urlopen(live_url + "/api/queries", timeout=2).status == 200
        except Exception:
            live_ok = False
    for s in live_scens:
        if not (live and live_ok):
            why = ("not requested (--live)" if not live
                   else f"no live backend at {live_url} — start ./ui/run.sh --live")
            result["skipped"].append({"name": s["name"], "why": why})

    srv = None
    port = None
    if offline:
        port = free_port()
        srv = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
             "--directory", STATIC],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for_server(f"http://127.0.0.1:{port}/"):
            srv.terminate()
            raise SystemExit("could not start the offline static server")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as e:
                msg = str(e).lower()
                if "executable doesn't exist" in msg or "playwright install" in msg:
                    say(f"SKIP — chromium not downloaded. Run:\n{INSTALL_HINT}")
                    return {"captured": [], "skipped": [s["name"] for s in wanted],
                            "errors": []}
                raise

            jobs = [(s, f"http://127.0.0.1:{port}/") for s in offline]
            if live and live_ok:
                jobs += [(s, live_url) for s in live_scens]

            for scen, url in jobs:
                r = capture_one(browser, url, scen, outdir, viewport, video=video)
                if r["status"] == "ok":
                    result["captured"].append(r["name"])
                    errs = r.get("console_errors") or []
                    say(f"  captured {r['name']}" +
                        (f"   ({len(errs)} console error(s))" if errs else ""))
                    if errs:
                        result.setdefault("console", {})[r["name"]] = errs
                else:
                    result["errors"].append(r)
                    say(f"  FAILED   {r['name']}  << {r['detail']}")
            browser.close()
    finally:
        if srv:
            srv.terminate()

    for s in result["skipped"]:
        say(f"  skipped  {s['name']}  ({s['why']})")

    with open(os.path.join(outdir, "_capture.json"), "w") as f:
        json.dump(result, f, indent=2)
    return result


def main():
    ap = argparse.ArgumentParser(description="Capture UI scenarios to PNG + text.")
    ap.add_argument("outdir")
    ap.add_argument("-s", "--scenarios", help="comma-separated names (default: all)")
    ap.add_argument("--live", action="store_true",
                    help="also capture scenarios needing ./ui/run.sh --live")
    ap.add_argument("--all-live", action="store_true",
                    help="capture EVERY scenario against the live backend, including "
                         "ones that could run offline (implies --live)")
    ap.add_argument("--base-url", default=None,
                    help="live server URL (default http://127.0.0.1:8000)")
    ap.add_argument("--video", action="store_true", help="also record .webm per scenario")
    ap.add_argument("--list", action="store_true", help="list the catalogue and exit")
    a = ap.parse_args()

    if a.list:
        cat, _ = load_catalogue()
        for s in cat["scenarios"]:
            print(f"  {s['name']:<18} [{s.get('needs','offline'):<7}] {s.get('about','')}")
        return

    names = [n.strip() for n in a.scenarios.split(",")] if a.scenarios else None
    r = capture(a.outdir, names=names, live=a.live, base_url=a.base_url, video=a.video,
                all_live=a.all_live)
    print(f"\n{len(r['captured'])} captured, {len(r['skipped'])} skipped, "
          f"{len(r['errors'])} failed  ->  {a.outdir}")
    sys.exit(1 if r["errors"] else 0)


if __name__ == "__main__":
    main()
