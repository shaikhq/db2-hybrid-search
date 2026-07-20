# Installation — Hybrid Search on Db2 12.1.5

One ordered guide to stand this project up on a fresh machine:
**prerequisites → per-component install → configure → start → verify.**
Each component also has an automated installer **in this folder**
(`opensearch-install.sh`, `db2-install.sh`, `llamacpp-install.sh`) that installs,
verifies, then leaves the service stopped (`0_start-services.sh` starts them for a run).

> Run everything **as the Db2 instance owner** (e.g. `db2inst1`). The Text-Search
> admin steps and the fast local connection require it.

---

## 0. Prerequisites

| Item | Requirement |
|---|---|
| **OS** | Linux x86-64 (developed on Red Hat Linux 10 / RHEL-family). |
| **CPU / RAM** | CPU-only is fine (no GPU). ~2 GB free RAM for OpenSearch; a few GB for Db2. The llama.cpp servers are small. |
| **Python** | 3.12 (`pip install -e .` pulls `ibm_db`, FastAPI, uvicorn). |
| **Build tools** | `git`, `cmake`, a C/C++ toolchain (for llama.cpp). |
| **Disk** | ~1 GB OpenSearch, Db2 install media, models (~37 MB embedding, ~438 MB reranker, ~2 GB generation if used). |
| **Internet** | To download OpenSearch, the models, and clone llama.cpp. |

### Ports used

| Port | Service | Started by |
|---|---|---|
| `25010` (example) | Db2 instance (yours may differ — look up `SVCENAME`) | Db2 |
| `9200` | OpenSearch (Db2 Text Search backend) | `0_start-services.sh` |
| `8085` | llama.cpp **embedding** server (bge-small-en-v1.5) | `0_start-services.sh` |
| `8086` | llama.cpp **generation** server (Qwen2.5-3B) — *optional*, query-understanding | `scripts/query-understanding/start_gen_server.sh` |
| `8087` | llama.cpp **reranker** server (bge-reranker-v2-m3) — *optional*, search reranking | `scripts/rerank/start_rerank_server.sh` |

> **Important — llama.cpp runs as *separate* server processes on *different* ports.**
> `llama-server`'s `--embedding` and `--reranking` flags are **mutually exclusive** at
> launch, so the embedding server (:8085) and the reranker (:8087) are two independent
> processes. The generation server (:8086) is a third. Only the embedding server is
> required; the generation and reranker servers are optional (both features ship off
> by default).

```bash
git clone <your-repo-url> db2-hybrid-search && cd db2-hybrid-search
```

Install OpenSearch **before** Db2 (Db2 registers it as the Text Search backend).

---

## 1. OpenSearch (Db2 Text Search backend)

> **Shortcut:** `./install/opensearch-install.sh` automates all of the steps
> below — install, verify it starts, then leave it stopped.

OpenSearch is the backend for Db2 Text Search (the lexical/BM25 leg). ~10 minutes.
Needs ~2 GB free memory, ~1 GB disk, `curl`. It bundles Java.

> **WARNING** — this turns OFF OpenSearch security/passwords to keep local setup
> simple. Use only on a machine others can't reach over the network.

**1. Raise the memory-map limit** (or OpenSearch won't start):

```bash
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf
sudo sysctl -p /etc/sysctl.d/99-opensearch.conf     # verify: sysctl vm.max_map_count -> 262144
```

**2. Create a service account:**

```bash
sudo useradd --system --no-create-home --shell /sbin/nologin opensearch
```

**3. Download and unpack into /opt/opensearch:**

```bash
cd /opt
sudo wget https://artifacts.opensearch.org/releases/bundle/opensearch/3.7.0/opensearch-3.7.0-linux-x64.tar.gz
sudo tar -xzf opensearch-3.7.0-linux-x64.tar.gz
sudo mv opensearch-3.7.0 opensearch
sudo rm opensearch-3.7.0-linux-x64.tar.gz
sudo chown -R opensearch:opensearch /opt/opensearch
```

**4. Configure** — append to `/opt/opensearch/config/opensearch.yml` (single-node, security off):

```yaml
cluster.name: db2-text-search-cluster
node.name: node-1
network.host: 0.0.0.0
http.port: 9200
discovery.type: single-node
plugins.security.disabled: true
```

**5. Start (background) and check:**

```bash
sudo -u opensearch /opt/opensearch/bin/opensearch -d -p /opt/opensearch/opensearch.pid
# ~1 min to be ready the first time, then:
curl "http://localhost:9200"     # JSON showing node-1 / db2-text-search-cluster = running
```

Stop it: `sudo kill "$(cat /opt/opensearch/opensearch.pid)"`. Start again later by
rerunning the Step 5 command (no reinstall). You never query OpenSearch directly —
**Db2 Text Search owns the index.**

---

## 2. Db2 12.1.5 + instance + Text Search

> **Shortcut:** `sudo ./install/db2-install.sh /path/to/server_dec` scripts
> everything below — install, create the instance + `SAMPLE`, enable Text Search +
> register OpenSearch — then leaves Db2 stopped. Needs **root** and the extracted
> install media (`db2_install` may be interactive). Skip if Db2 is already installed
> (then enable Text Search + register OpenSearch by hand — `SYSTS_ENABLE` +
> `SYSTS_CREATE_SERVER`).

**1. Install Db2 and create the instance** (steps before `su - db2inst1` run as **root**):

```bash
tar -xvf v12.1.5_linuxx64_server_dec.tar.gz && cd server_dec
./db2_install                                    # accept defaults
useradd db2inst1 && passwd db2inst1
cd /opt/ibm/db2/V12.1/instance
./db2icrt -u db2inst1 -nosharedgroup db2inst1    # db2inst1 is also the fenced user
```

As **db2inst1** — enable the TCP/IP listener, set the port, restart:

```bash
su - db2inst1
db2set DB2COMM=TCPIP
db2 update dbm cfg using SVCENAME 50000          # your instance may differ — see "Find your Db2 port"
db2stop && db2start
```

**2. Create the sample database and test:**

```bash
db2sampl                                         # build the SAMPLE database
db2 connect to sample
db2 "SELECT * FROM employee FETCH FIRST 5 ROWS ONLY"   # should return 5 rows
```

**3. Enable the vector index registry var** (once per instance, before ingest):

```bash
db2set DB2_VECTOR_INDEXING=YES -immediate
```

**Find your Db2 port** (a typical instance uses e.g. `25010`, not 50000):

```bash
svc=$(db2 get dbm cfg | awk -F'= ' '/TCP\/IP Service name/{print $2}' | tr -d ' ')
grep "^$svc\b" /etc/services       # -> your DB2_PORT
```

---

## 3. llama.cpp + models (local, keyless)

> **Shortcut:** `./install/llamacpp-install.sh` builds llama.cpp, downloads
> the embedding model, verifies 384-dim, then stops the server.

Db2's `TO_EMBEDDING` calls a local llama.cpp server — no API keys, no network egress,
no per-call cost. Prerequisites: `git`, `cmake`, a C/C++ toolchain.

**1. Build llama.cpp (CPU)** — builds only `llama-server` (the piece the pipeline needs):

```bash
#   RHEL/Fedora:   sudo dnf install -y git cmake gcc-c++
#   Debian/Ubuntu: sudo apt-get install -y git cmake build-essential
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git ~/llama.cpp
cmake -S ~/llama.cpp -B ~/llama.cpp/build \
      -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DGGML_NATIVE=ON
cmake --build ~/llama.cpp/build --target llama-server -j"$(nproc)"
# -> ~/llama.cpp/build/bin/llama-server
```

**2. Download the embedding model** (bge-small-en-v1.5, ~37 MB, required):

```bash
mkdir -p ~/models/bge-small-en-v1.5
curl -fSL -o ~/models/bge-small-en-v1.5/bge-small-en-v1.5-q8_0.gguf \
  "https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/bge-small-en-v1.5-q8_0.gguf"
```

**3. Verify (384-dim)** — bring the server up on a throwaway port, embed once, check the dim:

```bash
~/llama.cpp/build/bin/llama-server \
  -m ~/models/bge-small-en-v1.5/bge-small-en-v1.5-q8_0.gguf \
  --embedding --pooling cls --ctx-size 512 --host 127.0.0.1 --port 8099 &
PID=$!
until curl -s -o /dev/null http://127.0.0.1:8099/health; do sleep 1; done
curl -s http://127.0.0.1:8099/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"input":"hello","model":"bge-small-en-v1.5"}' \
  | python3 -c "import sys,json;print('dim', len(json.load(sys.stdin)['data'][0]['embedding']))"
kill "$PID"   # -> dim 384
```

`--pooling cls` is **required** — bge uses CLS pooling; the wrong pooling silently
degrades retrieval quality. The run-time embedding server (`:8085`) is started by
`0_start-services.sh`; don't leave this verify server running. Env overrides:
`LLAMA_CPP_DIR`, `BGE_GGUF`, `EMBED_PORT`.

### Optional models (features off by default)

Both are separate `llama-server` processes on their own ports (see the mutual-exclusion
note in §0).

**Reranker** — `bge-reranker-v2-m3` (~438 MB), for the search-tab reranking stage:

```bash
mkdir -p ~/models/bge-reranker-v2-m3
curl -fSL -o ~/models/bge-reranker-v2-m3/bge-reranker-v2-m3-Q4_K_M.gguf \
  "https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF/resolve/main/bge-reranker-v2-m3-Q4_K_M.gguf"
scripts/rerank/start_rerank_server.sh    # --reranking on :8087; see scripts/rerank/README.md
```

**Generation** — `Qwen2.5-3B-Instruct` (~2 GB), for the query-understanding gated mode:

```bash
# download a Qwen2.5-3B-Instruct GGUF (Q4_K_M) into ~/models/qwen2.5-3b-instruct/, then:
scripts/query-understanding/start_gen_server.sh    # on :8086; see scripts/query-understanding/README.md
```

---

## 4. Python project

Python 3.12 venv for `eval.py` and the UI. Installing editable pulls in `ibm_db`,
FastAPI, uvicorn, and makes `hybrid_search` importable:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

> The headless UI E2E test (`tests/test_demo_e2e.py`) additionally needs Playwright
> + Chromium: `pip install playwright && python -m playwright install chromium`.

---

## 5. Configure `.env`

```bash
cp .env.example .env
$EDITOR .env
```

| Key | Value |
|---|---|
| `DB2_PORT` | your instance's port — do **not** assume 50000 (see "Find your Db2 port") |
| `DB2_PASSWORD` | the instance owner's Db2 password |
| _(embeddings)_ | none — local llama.cpp server, no API keys |

Defaults for `DB2_HOST`, `DB2_DATABASE=sample`, `DB2_SCHEMA=myschema`, `DB2_TABLE=chunks`,
the `HYBRID_*` fusion knobs, and the `QU_*` / `RERANK_*` feature flags (both off) are
usually fine. `.env` is git-ignored — real credentials are never committed. See
[`../.env.example`](../.env.example) for every key.

---

## 6. Start services & verify your setup

```bash
./scripts/0_start-services.sh        # Db2, OpenSearch, embedding server (idempotent)
```

Confirm all three are up:

```bash
db2gcf -s                                                                  # DB2 State : Available
curl -s -o /dev/null -w "opensearch: %{http_code}\n" http://localhost:9200
curl -s -o /dev/null -w "embeddings: %{http_code}\n" http://127.0.0.1:8085/health
```

**One-shot smoke test** (services up + a real hybrid search returns results):

```bash
./scripts/smoke-test.sh
```

Then run the pipeline (see the top-level [README](../README.md#usage)): `1_ingest.sql`
→ `2_search.sql` → `eval.py`, and `3_stop-services.sh` when done.

---

## Gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `DB2_PORT` connection fails | `.env.example` may ship a different default; real instances vary | Look up `SVCENAME` in `/etc/services` (§2) |
| `ModuleNotFoundError: ibm_db` from a wrapper | wrapper `sudo -iu`s into a **system** python lacking `ibm_db` | `pip install -e .` as the instance owner, or run the venv python with `DB2_HOST=local` |
| `ModuleNotFoundError: hybrid_search` | package not importable in that python | `pip install -e .` |
| `ibm_db` TCP connect hangs ~40s | slow TCP path on this setup | use `DB2_HOST=local` for the fast local connection |
| `TO_EMBEDDING` fails during ingest/search | embedding server not up on `:8085` | `./scripts/0_start-services.sh`; smoke-test the curl in §3 |
| Verify prints a dim other than 384 | wrong model file or missing `--pooling cls` | re-download the GGUF and pass the flag |
| reranker returns near-zero / identical scores | a broken GGUF conversion | use the `gpustack` bge-reranker-v2-m3 GGUF above; avoid unverified Qwen3-Reranker GGUFs |
