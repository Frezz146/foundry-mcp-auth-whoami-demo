#!/usr/bin/env bash
# Names and helpers for the Azure Container Apps test.
# Use it from the repo root:  source deploy/vars.sh
# Works in bash and zsh. Naming scheme: <customer>-<region>-<resource>-<topic>-<env>

# zsh treats # as a comment only when this is set; harmless in bash
setopt interactive_comments 2>/dev/null || true

export LOCATION="westeurope"
export RG="frezz-we-rg-mcpwhoami-dev"
export CAE="frezz-we-cae-mcpwhoami-dev"
# The custom domain of the Foundry resource must be globally unique. Add a suffix if Azure says CustomDomainInUse.
export FOUNDRY="frezz-we-ais-mcpwhoami-dev"
export PROJECT="frezz-we-proj-mcpwhoami-dev"
export FOUNDRY_LOCATION="$LOCATION"
export MODEL_NAME="gpt-5-mini"
export MODEL_VERSION="2025-08-07"
export APP="frezz-we-ca-mcpwhoami-dev"
export API_APP_NAME="frezz-we-app-mcpwhoami-api-dev"
export ROLE_VALUE="Mcp.Tools.ReadWrite.All"
export CONN_NAME="whoami-mcp"
# OAuth identity passthrough (post 3)
export CLIENT_APP_NAME="frezz-we-app-mcpwhoami-client-dev"
export SCOPE_VALUE="Mcp.Tools.Access"
export CONN_NAME_OAUTH="whoami-mcp-oauth"
export RG_TAG="foundry-mcp-whoami-demo"

# Values found along the way (ids, host names) live in deploy/.state.env, which git ignores.
# save KEY VALUE stores one value and exports it into the current shell.
save() {
  mkdir -p deploy
  { grep -v "^export $1=" deploy/.state.env 2>/dev/null; echo "export $1=\"$2\""; } > deploy/.state.tmp
  mv deploy/.state.tmp deploy/.state.env
  export "$1=$2"
}

if [ -f deploy/.state.env ]; then
  # shellcheck disable=SC1091
  source deploy/.state.env
fi
