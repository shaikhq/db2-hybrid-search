#!/usr/bin/env bash
# opensearch-install.sh — install & configure OpenSearch (the Db2 Text Search
# backend), verify it starts, then leave it STOPPED (0_start-services.sh runs it).
# One-time, single-node, security OFF (local use only). Red Hat Linux 10 + sudo.
# Idempotent: skips whatever is already done. See install/README.md.
set -euo pipefail

VERSION="${OPENSEARCH_VERSION:-3.7.0}"
HOME_DIR="${OPENSEARCH_HOME:-/opt/opensearch}"
PORT="${OPENSEARCH_PORT:-9200}"
# The whole stack runs as ONE user (default db2inst1, the Db2 instance owner), so
# there's no cross-user sudo to start/stop services. Db2's setup reuses this user.
OWNER="${OPENSEARCH_OWNER:-db2inst1}"

# Memory-map limit (or OpenSearch won't start).
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf >/dev/null
sudo sysctl -p /etc/sysctl.d/99-opensearch.conf >/dev/null

# Runtime user: create it if missing (OpenSearch must NOT run as root). If Db2 runs
# first, this is a no-op; if OpenSearch runs first, Db2's db2icrt reuses the user.
id "$OWNER" &>/dev/null || sudo useradd "$OWNER"

# Download + unpack into $HOME_DIR (skip if already installed).
if [ ! -x "$HOME_DIR/bin/opensearch" ]; then
  TARBALL="opensearch-${VERSION}-linux-x64.tar.gz"
  cd /opt
  sudo wget -q "https://artifacts.opensearch.org/releases/bundle/opensearch/${VERSION}/${TARBALL}"
  sudo tar -xzf "$TARBALL" && sudo rm "$TARBALL"
  sudo mv "opensearch-${VERSION}" "$HOME_DIR"
  sudo chown -R "$OWNER:$OWNER" "$HOME_DIR"
fi

# Configure: single-node, security disabled.
sudo -u "$OWNER" tee "$HOME_DIR/config/opensearch.yml" >/dev/null <<YML
cluster.name: db2-text-search-cluster
node.name: node-1
# localhost only: security is disabled below, and Db2 talks to OpenSearch on the
# same box, so it must never be network-reachable. (0.0.0.0 would expose an
# unauthenticated cluster to anything that can route to this host.)
network.host: 127.0.0.1
http.port: ${PORT}
discovery.type: single-node
plugins.security.disabled: true
YML

# Verify it starts (installs shouldn't leave a service running), then stop it.
# Started as $OWNER here (this script runs as root); at runtime 0_start-services.sh
# runs AS $OWNER, so it needs no sudo — that's the whole point.
echo "Verifying OpenSearch starts (first start takes ~1 min)…"
sudo -u "$OWNER" "$HOME_DIR/bin/opensearch" -d -p "$HOME_DIR/opensearch.pid"
until curl -s -o /dev/null "http://localhost:${PORT}"; do sleep 2; done
sudo kill "$(cat "$HOME_DIR/opensearch.pid")"
echo "OK — OpenSearch installed and verified on :${PORT} as '$OWNER' (now stopped)."
