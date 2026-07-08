#!/usr/bin/env bash
# opensearch-install.sh — install & configure OpenSearch (the Db2 Text Search
# backend), verify it starts, then leave it STOPPED (0_start-services.sh runs it).
# One-time, single-node, security OFF (local use only). Red Hat Linux 10 + sudo.
# Idempotent: skips whatever is already done. See docs/opensearch-setup.md.
set -euo pipefail

VERSION="${OPENSEARCH_VERSION:-3.7.0}"
HOME_DIR="${OPENSEARCH_HOME:-/opt/opensearch}"
PORT="${OPENSEARCH_PORT:-9200}"

# Memory-map limit (or OpenSearch won't start).
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf >/dev/null
sudo sysctl -p /etc/sysctl.d/99-opensearch.conf >/dev/null

# Service account.
id opensearch &>/dev/null || sudo useradd --system --no-create-home --shell /sbin/nologin opensearch

# Download + unpack into $HOME_DIR (skip if already installed).
if [ ! -x "$HOME_DIR/bin/opensearch" ]; then
  TARBALL="opensearch-${VERSION}-linux-x64.tar.gz"
  cd /opt
  sudo wget -q "https://artifacts.opensearch.org/releases/bundle/opensearch/${VERSION}/${TARBALL}"
  sudo tar -xzf "$TARBALL" && sudo rm "$TARBALL"
  sudo mv "opensearch-${VERSION}" "$HOME_DIR"
  sudo chown -R opensearch:opensearch "$HOME_DIR"
fi

# Configure: single-node, security disabled.
sudo -u opensearch tee "$HOME_DIR/config/opensearch.yml" >/dev/null <<YML
cluster.name: db2-text-search-cluster
node.name: node-1
network.host: 0.0.0.0
http.port: ${PORT}
discovery.type: single-node
plugins.security.disabled: true
YML

# Verify it starts (installs shouldn't leave a service running), then stop it.
echo "Verifying OpenSearch starts (first start takes ~1 min)…"
sudo -u opensearch "$HOME_DIR/bin/opensearch" -d -p "$HOME_DIR/opensearch.pid"
until curl -s -o /dev/null "http://localhost:${PORT}"; do sleep 2; done
sudo kill "$(cat "$HOME_DIR/opensearch.pid")"
echo "OK — OpenSearch installed and verified on :${PORT} (now stopped)."
