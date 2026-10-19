#!/usr/bin/env bash
# Build and start the server in Docker (OrbStack), call it with your az login, then stop it again.
set -euo pipefail
cd "$(dirname "$0")/.."

URL="${MCP_URL:-http://localhost:8000/mcp}"
export TENANT_ID="${TENANT_ID:-$(az account show --query tenantId -o tsv)}"

diagnose() {
  echo "--- container state"
  docker compose ps -a || true
  echo "--- container logs"
  docker compose logs --tail 60 whoami || true
  echo "--- what listens on port 8000 on this Mac"
  lsof -nP -iTCP:8000 -sTCP:LISTEN || true
}

if ! docker compose up -d --build --wait --wait-timeout 60; then
  diagnose
  docker compose down
  exit 1
fi
trap 'docker compose down' EXIT

echo "--- without a token (expect 401)"
code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 -m 10 -X POST "$URL" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{}' || true)
echo "HTTP $code"
if [ "$code" != "401" ]; then
  diagnose
  exit 1
fi

echo "--- as the user you are signed in with in az"
uv run scripts/call_whoami.py user
