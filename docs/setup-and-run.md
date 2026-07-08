# Setup & Run — End to End

A repeatable runbook for standing up the app on a fresh VM and running it, via the
setup docs and the numbered pipeline. Consolidates [README.md](../README.md) with
the practical gotchas from a real single-user Db2 VM.

Everything runs **as the Db2 instance owner** (e.g. `db2inst1`) — the text-search
and local-connection steps require it.

---

## Two decisions that shape the run

1. **Do you want the semantic leg?** It needs the local embedding server (started
   by `0_start-services.sh`).
   - **No** → lexical-only: delete the model/embed/vector sections in
     `1_ingest.sql` (keep table + text index); add semantic later.
2. **Is Db2 / OpenSearch already installed?** If so, skip those setups below — but
   you still need Text Search enabled + OpenSearch registered (`SYSTS_ENABLE` +
   `SYSTS_CREATE_SERVER` — see [db2-setup.md](db2-setup.md)).

---

## Step 1 — Install the prerequisites (one-time)

Each installer under `scripts/install/` installs, verifies, then
**leaves the service stopped** — `0_start-services.sh` starts them for the run.
Install OpenSearch before Db2 (Db2 registers it as the Text Search backend):

```bash
git clone <repo-url> hybrid-search && cd hybrid-search
./scripts/install/opensearch-install.sh                     # OpenSearch (Text Search backend)
sudo ./scripts/install/db2-install.sh /path/to/server_dec   # Db2 + instance + SAMPLE + Text Search
./scripts/install/llamacpp-install.sh                       # build llama.cpp + download bge-small
```

- `db2-install.sh` needs **root** and the extracted install media; `db2_install`
  may be interactive. Skip if Db2 is already installed (then enable Text Search +
  register OpenSearch by hand — see [db2-setup.md](db2-setup.md)).
- Details: [db2-setup.md](db2-setup.md), [opensearch-setup.md](opensearch-setup.md),
  [llamacpp-setup.md](llamacpp-setup.md).
- **Python 3.12 venv** for `eval.py` and the UI — install the project editable
  (pulls in `ibm_db`, FastAPI, uvicorn, and makes `hybrid_search` importable):

  ```bash
  python3.12 -m venv .venv
  source .venv/bin/activate
  pip install -e .
  ```

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
./scripts/0_start-services.sh        # Db2, OpenSearch, embedding server (idempotent)
```

Confirm all three are up:

```bash
db2gcf -s                                              # DB2 State : Available
curl -s -o /dev/null -w "opensearch: %{http_code}\n" http://localhost:9200
curl -s -o /dev/null -w "embeddings: %{http_code}\n" http://127.0.0.1:8085/health
```

Stop them with `./scripts/3_stop-services.sh`.

---

## Step 4 — Ingest the corpus

Provide your corpus as a two-column CSV (`chunk_id, chunk_text`) named
`data/sample_chunks.csv` at the repo root (one is included), then:

```bash
db2 -tvf scripts/1_ingest.sql
```

`1_ingest.sql` clears any old table, `IMPORT`s the chunks, builds the Text Search
index (`SYSTS_CREATE`/`SYSTS_UPDATE`), registers the local embedding model
(`PROVIDER OPENAI` → llama.cpp), fills a `VECTOR(384)` column via `TO_EMBEDDING`,
and builds the vector index. Expect every row to end with a non-null embedding.

**Notes:**
- Once per instance: `db2set DB2_VECTOR_INDEXING=YES -immediate` (enables the
  vector index). The ingest needs this registry var.
- Reads a **fixed** `data/sample_chunks.csv` — rename your CSV to that or edit the
  `IMPORT FROM` line. For lexical-only, delete the model/embed/vector steps.

---

## Step 5 — Search & evaluate

```bash
db2 -tvf scripts/2_search.sql        # lexical / vector / hybrid for the query hardcoded in the SQL
```

Edit the query text in `2_search.sql` to search something else; for dynamic ad-hoc
queries use the live demo UI (Step 6).

> ⚠️ **Run `eval.py` from the venv** (it imports `ibm_db`), with `DB2_HOST=local`
> for the fast (~0.4s) local connection instead of the slow `ibm_db` TCP path:

```bash
source .venv/bin/activate                   # provides ibm_db + the installed hybrid_search
DB2_HOST=local python scripts/eval.py       # known_item: MRR/Hits@1 · topical: Recall@5/nDCG@5, per leg
```

Reports the held-out slice (never tuned on), TRAIN, and ALL. Results are
corpus-dependent — see [eval-results.md](eval-results.md) for the current numbers
and which leg wins.

---

## Step 6 — Demo UI

**Offline** (default — frozen fixtures, no Db2 at view time). Rebuild fixtures
first. With the project installed (`pip install -e .`), the engine imports
cleanly — no `PYTHONPATH` needed:

```bash
cd ui
DB2_HOST=local python build_fixtures.py   # → ui/fixtures.json
cp fixtures.json static/fixtures.json && cp queries.json static/queries.json
./run.sh                        # static UI + fixtures → http://127.0.0.1:8000
```

**Live** (typed ad-hoc queries hit the real engine) — run uvicorn against the venv
instead of `./ui/run.sh --live`:

```bash
cd ui
DB2_HOST=local python -m uvicorn api:app --host 127.0.0.1 --port 8000
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
| `ModuleNotFoundError: ibm_db` from `build_fixtures.sh` | The wrapper `sudo -iu <owner>`s into a **system** python lacking `ibm_db` | Install into that python (`pip install -e .` as the instance owner), or run the venv Python directly with `DB2_HOST=local` |
| `ModuleNotFoundError: hybrid_search` running a UI Python file directly | The engine package isn't importable in that python | `pip install -e .`, or run via the staging wrappers (they copy the package in) |
| UI "not running" in browser but `curl 127.0.0.1:8000` → 200 on the VM | Server bound to VM loopback; laptop can't reach it | Forward port 8000 (VS Code Ports) or bind `0.0.0.0` |
| `ibm_db` TCP connect hangs ~40s | Slow TCP path on this setup | Use `DB2_HOST=local` for the fast local connection |
| `TO_EMBEDDING` fails during ingest/search | Embedding server not up on `:8085` | `./scripts/0_start-services.sh`; smoke-test with the curl in [llamacpp-setup.md](llamacpp-setup.md) |

---

## Quick reference — prepared VM

```bash
cd /path/to/hybrid-search
./scripts/0_start-services.sh                  # Db2, OpenSearch, embedding server
db2 -tvf scripts/1_ingest.sql                  # cleanup + load + index + embed
db2 -tvf scripts/2_search.sql                  # hybrid search demo
DB2_HOST=local python scripts/eval.py          # metrics (venv active)
./scripts/3_stop-services.sh                   # stop everything when done

# UI (live):
cd ui && DB2_HOST=local python -m uvicorn api:app --host 127.0.0.1 --port 8000
```
