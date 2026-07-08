# Install-script test log

Uninstall each component, then reinstall **only** via its `0_*-install.sh` script,
to verify the script works from scratch. Fixes to scripts are recorded here.

Date: 2026-07-07 · Host: shaikh-sandbox (single-user, db2inst1)

---

## db2 — ⛔ SKIPPED (cannot test safely here)

**Reason:** `0_db2-install.sh` requires the Db2 install media
(`sudo ./scripts/0_db2-install.sh /path/to/server_dec`). That media is **not on
this machine** (no `db2_install`, no `server_dec`, no media tarball found).

Uninstalling Db2 (`db2idrop` + `db2_deinstall`) would therefore be **unrecoverable**
via the script, and would destroy the SAMPLE database and the `myschema.chunks`
corpus. Not done.

**To validate `0_db2-install.sh`:** run it on a throwaway VM that has the extracted
install media. The script itself is reviewed statically below.
- Static review: script is syntax-clean; runs `db2_install` (may be interactive on
  some media — a response file may be needed), `db2icrt`, `db2sampl`, then enables
  Text Search + registers OpenSearch and `db2stop`s. Caveat already noted in its header.

---

## docling — ✅ PASS (no fix needed)

- **Uninstall:** `rm -rf .venv`
- **Reinstall:** `./scripts/0_docling-install.sh` → exit 0. Recreated the venv,
  installed CPU torch + `requirements.txt`, and its own check printed
  `OK — docling + deps installed in .venv`.
- **Verify:** `docling`, `ibm_db`, `transformers`, `fastapi`, `uvicorn` all import;
  `hybrid_core` imports with `PYTHONPATH=scripts` (expected).
- No changes to the script.

---

## llamacpp — ✅ PASS (no fix needed)

- **Uninstall:** `rm -rf ~/llama.cpp ~/models/bge-small-en-v1.5`
- **Reinstall:** `./scripts/0_llamacpp-install.sh` → exit 0. Cloned + built
  `llama-server`, downloaded the GGUF (35 MB), and its own verify printed
  `OK — llama.cpp + bge-small serve 384-dim embeddings (server left stopped)`.
- **Verify:** binary + GGUF present; verify server on :8099 correctly stopped.
- No changes to the script.

---

## opensearch — ✅ PASS (no fix needed)

- **Uninstall:** stopped it, then `rm -rf /opt/opensearch`, `userdel opensearch`,
  `rm /etc/sysctl.d/99-opensearch.conf` (clean-room).
- **Reinstall:** `./scripts/0_opensearch-install.sh` → exit 0. Re-created the user,
  set the sysctl limit, downloaded + unpacked OpenSearch 3.7.0, wrote the config,
  and its own verify printed
  `OK — OpenSearch installed and verified on :9200 (now stopped)`.
- **Verify:** installed, user exists, `plugins.security.disabled: true` present in
  `opensearch.yml`, and left stopped. (Note: read the config with `sudo` — it's
  owned by the `opensearch` user.)
- No changes to the script.

---

## Summary

| component | result | script fix |
|-----------|--------|-----------|
| db2       | ⛔ skipped — no install media on this host (unrecoverable) | none (validate on a VM with media) |
| docling   | ✅ PASS | none |
| llamacpp  | ✅ PASS | none |
| opensearch| ✅ PASS | none |

All three testable install scripts worked from scratch with **no fixes required**.
Db2 could not be tested here without the install media. After the tests, the app
was restored (start-services + re-ingest).

