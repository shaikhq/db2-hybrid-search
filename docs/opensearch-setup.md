# Install OpenSearch (for Db2 Text Search)

OpenSearch is the backend for Db2 Text Search (the lexical/BM25 leg). This sets it
up locally on Red Hat Linux 10 — about 10 minutes. Run each block in order.

> **Shortcut:** `./scripts/0_opensearch-install.sh` automates all of the steps below.

> [!WARNING]
> This turns OFF OpenSearch security/passwords to keep local setup simple. Use it
> only on a machine others can't reach over the network.

**Needs:** ~2 GB free memory, ~1 GB disk, an internet connection, and `curl`.
OpenSearch bundles everything else (including Java).

## 1. Raise the memory-map limit

OpenSearch opens more files than the Linux default allows; raise it once or it
won't start:

```bash
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf
sudo sysctl -p /etc/sysctl.d/99-opensearch.conf     # verify: sysctl vm.max_map_count -> 262144
```

## 2. Create a service account

```bash
sudo useradd --system --no-create-home --shell /sbin/nologin opensearch
```

## 3. Download and unpack into /opt/opensearch

```bash
cd /opt
sudo wget https://artifacts.opensearch.org/releases/bundle/opensearch/3.7.0/opensearch-3.7.0-linux-x64.tar.gz
sudo tar -xzf opensearch-3.7.0-linux-x64.tar.gz
sudo mv opensearch-3.7.0 opensearch
sudo rm opensearch-3.7.0-linux-x64.tar.gz
sudo chown -R opensearch:opensearch /opt/opensearch
```

## 4. Configure

Append to `/opt/opensearch/config/opensearch.yml` (single-node, security off):

```yaml
cluster.name: db2-text-search-cluster
node.name: node-1
network.host: 0.0.0.0
http.port: 9200
discovery.type: single-node
plugins.security.disabled: true
```

## 5. Start (background) and check

```bash
sudo -u opensearch /opt/opensearch/bin/opensearch -d -p /opt/opensearch/opensearch.pid
# ~1 min to be ready the first time, then:
curl "http://localhost:9200"     # JSON showing node-1 / db2-text-search-cluster = running
```

## Using it with this project

You don't query OpenSearch directly — **Db2 Text Search owns the index**.
`0_db2-install.sh` enables Text Search and registers OpenSearch as the Db2 backend;
then `4_ingest.sql` builds and fills the keyword index. See the main
[README](../README.md).

## Start / stop

```bash
sudo kill "$(cat /opt/opensearch/opensearch.pid)"    # stop
# start again later: rerun the Step 5 command — no reinstall needed
```
