#!/usr/bin/env python3
"""Live backend for the demo (`./ui/run.sh --live`) — a thin wrapper over the
search engine returning the SAME JSON shape as fixtures.json, so the frontend is
identical offline or live. The default demo is offline (static page + fixtures);
this exists for ad-hoc queries during Q&A."""

import json
import logging
import os

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
import ibm_db

import hybrid_core as h
import build_fixtures as bf   # responses_for()

# Log hybrid_core's SQL to the uvicorn console (reuse uvicorn's handler; fall
# back to a basic one if run standalone).
_uvicorn_handlers = logging.getLogger("uvicorn").handlers
if _uvicorn_handlers:
    h.log.handlers = _uvicorn_handlers
    h.log.propagate = False
else:
    logging.basicConfig(level=logging.INFO)
    h.log.propagate = True
h.log.setLevel(logging.INFO)

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "queries.json")) as f:
    DECK = json.load(f)
GOLD = {item["query"]: set(item["gold_chunk_ids"]) for item in DECK}

app = FastAPI(title="Db2 Hybrid Search Demo", docs_url="/docs")


@app.get("/api/queries")
def queries():
    """The curated demo deck (query, type, gold chunk IDs, note)."""
    return DECK


@app.get("/api/search")
def search(q: str = Query(..., description="search text"), k: int = bf.K):
    """All three strategy responses for a query (lexical, vector, hybrid).
    gold_chunk_ids come from the curated set when the query matches one."""
    gold = GOLD.get(q, set())
    conn = h.connect()
    try:
        modes = bf.responses_for(conn, q, gold)
    finally:
        ibm_db.close(conn)
    return {"query": q, "gold_chunk_ids": sorted(gold), **modes}


# Serve the same static UI; API routes above take precedence over this mount.
app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True), name="static")
