#!/usr/bin/env python3
"""Freeze the Evaluate tab into ui/static/eval_fixtures.json (offline-safe).

Runs every available test set through all three Db2 legs and stores exactly the payload
GET /api/evaluate returns, so `./ui/run.sh` — the offline conference path — shows real
numbers with no Db2. Live mode recomputes on demand.

Reuses api.py's own endpoint functions rather than reimplementing them: whatever the
live tab would show is what gets frozen.

Run: PYTHONPATH=src DB2_HOST=local .venv/bin/python ui/build_eval_fixtures.py
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

import api  # noqa: E402


def main():
    available = api.eval_sets()["sets"]
    stamp = datetime.date.today().isoformat()
    out = {"computed": stamp, "available": available, "sets": {}}
    for name in available:
        payload = api.evaluate(name=name)
        payload["computed"] = stamp
        out["sets"][name] = payload
        blocks = payload["blocks"]["all"]
        print(f"  {name:16} {payload['queries']:4} queries · "
              + " · ".join(f"{leg} nDCG@5="
                           + ("—" if blocks[leg]['ndcg'] is None else f"{blocks[leg]['ndcg']:.3f}")
                           for leg in payload["legs"]), file=sys.stderr)

    dest = os.path.join(HERE, "static", "eval_fixtures.json")
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, dest)
    print(f"wrote {len(out['sets'])} set(s) -> {os.path.relpath(dest, os.path.dirname(HERE))}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
