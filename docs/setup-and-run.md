# Setup & Run — End to End

A complete, repeatable runbook for standing up the hybrid-search app on a fresh
VM and running it, from prerequisites through the demo UI. This consolidates
[README.md](../README.md) with the practical gotchas you hit on a real
single-user Db2 VM.

> Assumes **IBM Db2 12.1.5** and **OpenSearch** are already installed. For
> installing those from scratch, see [db2-setup.md](db2-setup.md) and
> [opensearch-setup.md](opensearch-setup.md).

---

## Two decisions that shape the whole run

1. **Do you have watsonx.ai credentials (API key + project id)?**
   - **Yes** → full hybrid search (lexical **and** semantic legs).
   - **No** → set `SKIP_EMBEDDING=1` in `.env` for **lexical-only**; add semantic later.
2. **Are you logged in *as* the Db2 instance owner (e.g. `db2inst1`)?**
   - On a single-user VM, **yes** — and that means the `*.sh` search wrappers
     (`search.sh`, `eval.sh`, `build_fixtures.sh`) won't work as written. Use the
     `DB2_HOST=local python ...` direct-invoke form shown throughout. See
     [Gotchas](#gotchas--why).

Everything below must run **as the Db2 instance owner** — the text-index steps
use a local Db2 connection and the `db2ts` tooling, which require it.

---

## Step 0 — Confirm prerequisites

```bash
whoami                       # must be the Db2 instance owner (e.g. db2inst1)
db2level                     # expect "DB2 v12.1.5.x"
db2gcf -s                    # expect: DB2 State : Available
python3 --version            # need Python 3.12
curl -s -o /dev/null -w "OpenSearch: %{http_code}\n" http://localhost:9200   # expect 200
```

**Find your Db2 TCP port** — do *not* assume the `.env.example` default of 50000;
a typical instance uses something else (e.g. `25010`):

```bash
svc=$(db2 get dbm cfg | awk -F'= ' '/TCP\/IP Service name/{print $2}' | tr -d ' ')
grep "^$svc\b" /etc/services       # → your DB2_PORT
```

**Have watsonx.ai ready** (for the semantic leg): an API key, a project id, and an
embedding model (default `sentence-transformers/all-minilm-l6-v2`, 384-dim). Skip
if going lexical-only.

---

## Step 1 — System library for Docling / OpenCV

```bash
# RHEL / Fedora:
sudo dnf install -y libglvnd-glx
# Debian / Ubuntu:
# sudo apt-get install -y libgl1
```

`libGL.so.1` is required by Docling's OpenCV dependency, used by the PDF
**extract/chunk** steps. If you ingest a pre-built `.chunks.csv` you can skip
those steps — but `pip` still installs `opencv-python`, so install the lib anyway.

---

## Step 2 — Python virtual environment + dependencies

```bash
cd /path/to/hybrid-search
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# Install CPU-only torch FIRST so pip doesn't pull multi-GB CUDA wheels:
pip install --index-url https://download.pytorch.org/whl/cpu torch==2.12.1 torchvision==0.27.1
pip install -r requirements.txt

# Sanity check:
python -c "import ibm_db, docling, transformers; print('imports OK')"
```

---

## Step 3 — Configure `.env`

```bash
cp .env.example .env
$EDITOR .env
```

Fill in:

| Key | Value |
|-----|-------|
| `DB2_PORT` | the port from Step 0 |
| `DB2_PASSWORD` | the instance owner's Db2 password |
| `WATSONX_APIKEY`, `WATSONX_PROJECT_ID` | your watsonx creds — **or** add `SKIP_EMBEDDING=1` for lexical-only |

Defaults for `DB2_HOST=localhost`, `DB2_DATABASE=sample`, `DB2_SCHEMA=myschema`,
`DB2_TABLE=chunks`, and the `HYBRID_*` fusion knobs are usually fine. `.env` is
git-ignored — credentials are never committed.

Verify the connection:

```bash
db2 connect to sample && db2 connect reset      # expect "Connection ... successful"
```

---

## Step 4 — One-time Db2 setup (Text Search + OpenSearch)

```bash
./scripts/1_cleanup.sh        # idempotent clean slate (drops index then table if present)
./scripts/2_setup.sh          # enable Db2 Text Search + register OpenSearch as the backend
```

`2_setup.sh` only needs to succeed once per database; it's safe to re-run.

---

## Step 5 — Ingest the corpus

**From a PDF** (full pipeline — the intermediate `.md` and `.chunks.csv` are
inspectable):

```bash
python scripts/3_extract.py your-doc.pdf           # PDF → your-doc.md   (needs libGL)
python scripts/4_chunk.py   your-doc.md            # .md  → your-doc.chunks.csv
python scripts/5_ingest.py  your-doc.chunks.csv    # → Db2: rows + text index + vectors
```

**Or ingest a ready-made CSV** (e.g. the repo's sample corpus) — skips extract/chunk:

```bash
python scripts/5_ingest.py LLM_Integration.chunks.csv
```

Step 5 loads the chunks into `myschema.chunks`, builds the Db2 Text Search index,
registers the watsonx embedding model, and fills a `VECTOR(384)` column. This is
the **first external call to watsonx.ai**. (With `SKIP_EMBEDDING=1` it stops after
the text index.) Expect a final line like:

```
Done: 101 chunks with text + vector + vector index in myschema.chunks
```

---

## Step 6 — Search & evaluate

> ⚠️ **Do not use `./scripts/search.sh` / `./scripts/eval.sh` on a single-user VM.**
> They assume you log in as a *different* user and `sudo -iu <owner>` into a
> **system-wide** `ibm_db`. When you already *are* the instance owner with
> `ibm_db` only inside the venv, they fail with `ModuleNotFoundError: ibm_db`.
> Run the Python directly instead (see [Gotchas](#gotchas--why)):

```bash
source .venv/bin/activate

# Ad-hoc query — prints lexical / vector / hybrid rankings with scores:
DB2_HOST=local python scripts/6_search.py "what privilege do I need to call TO_EMBEDDING"

# Quality metrics on the golden set (MRR, Recall@5, Hits@1 per leg + fusion):
DB2_HOST=local python scripts/eval.py
```

`DB2_HOST=local` forces the fast (~0.4s) **local** Db2 connection instead of the
slow `ibm_db` TCP connect. On the sample corpus, expect hybrid to beat both single
legs on every metric (hybrid MRR ≈ 0.89 vs vector ≈ 0.68 vs lexical ≈ 0.51).

---

## Step 7 — Demo UI

### Offline mode (default — frozen fixtures, no Db2 at view time)

Rebuild the fixtures against your corpus first. The `build_fixtures.sh` wrapper has
the same sudo issue, so invoke the Python directly with `scripts/` on the path:

```bash
cd ui
source ../.venv/bin/activate
DB2_HOST=local PYTHONPATH=../scripts python build_fixtures.py   # writes ui/fixtures.json
cp fixtures.json static/fixtures.json
cp queries.json  static/queries.json
cd ..

./ui/run.sh                    # serves static UI + fixtures → http://127.0.0.1:8000
```

### Live mode (typed ad-hoc queries hit the real engine)

Run uvicorn directly against the venv instead of `./ui/run.sh --live`:

```bash
cd ui
source ../.venv/bin/activate
DB2_HOST=local PYTHONPATH=../scripts python -m uvicorn api:app --host 127.0.0.1 --port 8000
# UI at http://127.0.0.1:8000 · Swagger at http://127.0.0.1:8000/docs
```

### Viewing the UI from your laptop (remote VM)

The server binds to `127.0.0.1` **on the VM**, so a browser on your laptop can't
reach it directly. Two options:

- **VS Code Remote:** open the **Ports** panel → **Forward a Port** → `8000`, then
  click the forwarded `localhost:8000` link. (Background processes started outside
  the integrated terminal are often not auto-forwarded — add it manually.)
- **Direct network access:** start the server with `--host 0.0.0.0` and open port
  8000 in the VM's firewall/security group. Only do this on a trusted network.

**Stop a running UI server:** `fuser -k 8000/tcp`

---

## Gotchas & why

| Symptom | Cause | Fix |
|---------|-------|-----|
| `DB2_PORT` connection fails | `.env.example` ships `50000`; real instances differ | Look up `SVCENAME` in `/etc/services` (Step 0) |
| `ModuleNotFoundError: No module named 'ibm_db'` from `search.sh`/`eval.sh`/`build_fixtures.sh` | Wrappers `sudo -iu <owner>` into a **system** python that lacks the venv's `ibm_db` | Run `DB2_HOST=local python scripts/6_search.py …` (and `eval.py`) directly in the venv |
| `ModuleNotFoundError: No module named 'hybrid_core'` running `build_fixtures.py` directly | It imports `hybrid_core` expecting it alongside (the wrapper stages it into `/tmp`) | Add `PYTHONPATH=../scripts` |
| UI "not running" in browser but `curl 127.0.0.1:8000` returns 200 on the VM | Server bound to VM loopback; laptop can't reach it | Forward port 8000 (VS Code Ports) or bind `0.0.0.0` |
| `ibm_db` TCP connect hangs ~40s | Slow TCP path on this setup | Use `DB2_HOST=local` for the fast local connection |
| Docling import error about `libGL.so.1` | OpenCV system lib missing | `sudo dnf install -y libglvnd-glx` (Step 1) |

---

## Quick reference — full run on a prepared VM

```bash
cd /path/to/hybrid-search
source .venv/bin/activate

./scripts/1_cleanup.sh
./scripts/2_setup.sh
python scripts/5_ingest.py LLM_Integration.chunks.csv

DB2_HOST=local python scripts/6_search.py "how do I turn text into vectors"
DB2_HOST=local python scripts/eval.py

# UI (live):
cd ui && DB2_HOST=local PYTHONPATH=../scripts python -m uvicorn api:app --host 127.0.0.1 --port 8000
```
