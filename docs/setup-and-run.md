# Setup & Run — End to End

A repeatable runbook for standing up the app on a fresh VM and running it, via the
`scripts/*-install.sh` installers and the numbered pipeline. Consolidates
[README.md](../README.md) with the practical gotchas from a real single-user Db2 VM.

Everything runs **as the Db2 instance owner** (e.g. `db2inst1`) — the text-search
and local-connection steps require it.

---

## Two decisions that shape the run

1. **Do you want the semantic leg?** It needs the local embedding server (started
   by `1_start-services.sh`).
   - **No** → lexical-only: delete the model/embed/vector sections in
     `4_ingest.sql` (keep table + text index); add semantic later.
2. **Is Db2 / OpenSearch already installed?** If so, skip those installers below —
   but you still need Text Search enabled + OpenSearch registered (normally done by
   `0_db2-install.sh`; run `SYSTS_ENABLE` + `SYSTS_CREATE_SERVER` by hand if not).

---

## Step 1 — Install (one-time)

Each installer is idempotent and **leaves nothing running**:

```bash
git clone <repo-url> hybrid-search && cd hybrid-search
./scripts/0_docling-install.sh      # Python venv: Docling, ibm_db, UI deps (+ libGL)
./scripts/0_llamacpp-install.sh     # build llama.cpp + download bge-small-en-v1.5, verify
./scripts/0_opensearch-install.sh   # install + configure OpenSearch (Db2 Text Search backend)
sudo ./scripts/0_db2-install.sh /path/to/server_dec   # Db2 + instance + SAMPLE + Text Search
```

- `0_db2-install.sh` needs **root** and the extracted install media; `db2_install`
  may be interactive on your media. It also enables Text Search and registers
  OpenSearch. Skip if Db2 is already installed. See [db2-setup.md](db2-setup.md),
  [opensearch-setup.md](opensearch-setup.md), [local-embeddings.md](local-embeddings.md).

---

## Step 2 — Configure `.env`

```bash
cp .env.example .env
$EDITOR .env
```

| Key | Value |
|-----|-------|
| `DB2_PORT` | your instance's port — do **not** assume 50000 (see below) |
| `DB2_PASSWORD` | the instance owner's Db2 password |
| _(embeddings)_ | none — local llama.cpp server, no API keys |

Defaults for `DB2_HOST=localhost`, `DB2_DATABASE=sample`, `DB2_SCHEMA=myschema`,
`DB2_TABLE=chunks`, and the `HYBRID_*` fusion knobs are usually fine. `.env` is
git-ignored.

**Find your Db2 port** (a typical instance uses e.g. `25010`, not 50000):

```bash
svc=$(db2 get dbm cfg | awk -F'= ' '/TCP\/IP Service name/{print $2}' | tr -d ' ')
grep "^$svc\b" /etc/services       # → your DB2_PORT
```

---

## Step 3 — Start the services

```bash
./scripts/1_start-services.sh        # Db2, OpenSearch, embedding server (idempotent)
```

Confirm all three are up:

```bash
db2gcf -s                                              # DB2 State : Available
curl -s -o /dev/null -w "opensearch: %{http_code}\n" http://localhost:9200
curl -s -o /dev/null -w "embeddings: %{http_code}\n" http://127.0.0.1:8085/health
```

Stop them with `./scripts/stop-services.sh`.

---

## Step 4 — Ingest the corpus

**From a PDF** (the intermediate `.md` and `.chunks.csv` are inspectable):

```bash
source .venv/bin/activate
python scripts/2_extract.py your-doc.pdf           # PDF → your-doc.md
python scripts/3_chunk.py   your-doc.md            # .md  → your-doc.chunks.csv
db2 -tvf scripts/4_ingest.sql                      # → Db2: rows + text index + vectors
```

**Or ingest the repo's ready-made CSV** — skips extract/chunk:

```bash
db2 -tvf scripts/4_ingest.sql
```

`4_ingest.sql` clears any old table, `IMPORT`s the chunks, builds the Text Search
index (`SYSTS_CREATE`/`SYSTS_UPDATE`), registers the local embedding model
(`PROVIDER OPENAI` → llama.cpp), fills a `VECTOR(384)` column via `TO_EMBEDDING`,
and builds the vector index. Expect 101 rows with non-null embeddings.

**Notes:**
- Once per instance: `db2set DB2_VECTOR_INDEXING=YES -immediate` (enables the
  vector index). `1_start-services.sh` assumes Db2; the ingest needs this registry var.
- Reads a **fixed** `sample.chunks.csv` — rename your CSV to that or edit the
  `IMPORT FROM` line. For lexical-only, delete the model/embed/vector steps.

---

## Step 5 — Search & evaluate

```bash
db2 -tvf scripts/5_search.sql        # lexical / vector / hybrid for the query hardcoded in the SQL
```

Edit the query text in `5_search.sql` to search something else; for dynamic ad-hoc
queries use the live demo UI (Step 6).

> ⚠️ **Run `eval.py` from the venv** (it imports `ibm_db`), with `DB2_HOST=local`
> for the fast (~0.4s) local connection instead of the slow `ibm_db` TCP path:

```bash
source .venv/bin/activate
DB2_HOST=local python scripts/eval.py       # MRR, Recall@5, Hits@1 per leg + fusion
```

On the sample corpus, hybrid beats both single legs (MRR ≈ 0.81 vs vector ≈ 0.67
vs lexical ≈ 0.51).

---

## Step 6 — Demo UI

**Offline** (default — frozen fixtures, no Db2 at view time). Rebuild fixtures
first (the `build_fixtures.sh` wrapper hits the sudo/`ibm_db` issue, so invoke the
Python directly with `scripts/` on the path):

```bash
cd ui
DB2_HOST=local PYTHONPATH=../scripts python build_fixtures.py   # → ui/fixtures.json
cp fixtures.json static/fixtures.json && cp queries.json static/queries.json
./run.sh                        # static UI + fixtures → http://127.0.0.1:8000
```

**Live** (typed ad-hoc queries hit the real engine) — run uvicorn against the venv
instead of `./ui/run.sh --live`:

```bash
cd ui
DB2_HOST=local PYTHONPATH=../scripts python -m uvicorn api:app --host 127.0.0.1 --port 8000
# UI at http://127.0.0.1:8000 · Swagger at /docs
```

**Viewing from your laptop (remote VM):** the server binds to `127.0.0.1` on the
VM. In VS Code Remote, open **Ports** → **Forward a Port** → `8000` (background
processes are often not auto-forwarded — add it manually). Or bind `--host 0.0.0.0`
and open the firewall (trusted networks only). Stop it: `fuser -k 8000/tcp`.

---

## Gotchas & why

| Symptom | Cause | Fix |
|---------|-------|-----|
| `DB2_PORT` connection fails | `.env.example` ships `50000`; real instances differ | Look up `SVCENAME` in `/etc/services` (Step 2) |
| `ModuleNotFoundError: ibm_db` from `build_fixtures.sh` | The wrapper `sudo -iu <owner>`s into a **system** python lacking the venv's `ibm_db` | Run the Python directly with `DB2_HOST=local PYTHONPATH=../scripts` |
| `ModuleNotFoundError: hybrid_core` running a UI Python file directly | It imports `hybrid_core` from `scripts/` | Add `PYTHONPATH=../scripts` |
| UI "not running" in browser but `curl 127.0.0.1:8000` → 200 on the VM | Server bound to VM loopback; laptop can't reach it | Forward port 8000 (VS Code Ports) or bind `0.0.0.0` |
| `ibm_db` TCP connect hangs ~40s | Slow TCP path on this setup | Use `DB2_HOST=local` for the fast local connection |
| Docling import error about `libGL.so.1` | OpenCV system lib missing | `0_docling-install.sh` installs it (`libglvnd-glx`) |

---

## Quick reference — prepared VM

```bash
cd /path/to/hybrid-search
./scripts/1_start-services.sh                    # Db2, OpenSearch, embedding server
db2 -tvf scripts/4_ingest.sql                  # cleanup + load + index + embed
db2 -tvf scripts/5_search.sql                  # hybrid search demo
DB2_HOST=local python scripts/eval.py          # metrics (venv active)

# UI (live):
cd ui && DB2_HOST=local PYTHONPATH=../scripts python -m uvicorn api:app --host 127.0.0.1 --port 8000
```
