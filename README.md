# Foundry MCP auth demo: who does the tool see?

A tiny MCP server with one tool, `whoami`. It validates a real Microsoft Entra access token and tells
the caller what it sees: a **user** or only an **application**. That is the practical difference between
the MCP authentication methods in Microsoft Foundry.

| Method in Foundry | What the MCP server sees |
|---|---|
| Key based | A shared secret, no person |
| Microsoft Entra, agent identity | An application, no person |
| Microsoft Entra, project managed identity | An application, no person |
| OAuth identity passthrough | The signed in user |

Source for the table: [Set up authentication for MCP tools](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/mcp-authentication).

## Run it locally with Docker (OrbStack) and your az login

```bash
az login                      # once
scripts/try_with_az.sh        # builds, starts, calls as your az user, stops
```

Or step by step:

```bash
export TENANT_ID=$(az account show --query tenantId -o tsv)
docker compose up -d --build
uv run scripts/call_whoami.py user      # token of your az account, expect callerType "user"
docker compose down
```

For the application side set `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET` of a service
principal you already have and run `uv run scripts/call_whoami.py app`. Expect `callerType` `application`.

Identifiers are masked by default. Set `MASK_IDENTIFIERS=false` to see full values, and mask them again
before you publish a screenshot.

## Tests

```bash
uv run pytest
```

The tests sign their own tokens, so they need no tenant and no network. They cover missing, garbage,
expired, wrong audience, wrong tenant and wrongly signed tokens, plus the user and application cases.

## Settings

| Variable | Meaning | Default |
|---|---|---|
| `TENANT_ID` | Tenant whose tokens are accepted | required |
| `AUDIENCES` | Comma separated accepted `aud` values | required |
| `PUBLIC_URL` | URL of the MCP endpoint | `http://localhost:8000/mcp` |
| `MASK_IDENTIFIERS` | Mask ids and user names in the answer | `true` |
| `ALLOWED_HOSTS` | Host headers to allow when it runs behind a real host name | localhost only |
| `REQUIRED_ROLE` | App role (or scope) a valid token must also carry, otherwise `403` | off |
| `AUDIT_HEADER_VALUES` | Comma separated header names whose values appear in the audit line (experiments only, never credentials) | off |
| `JWKS_URI` | Override the key endpoint, for tests | tenant default |

## Read this before you reuse it

- For the local test the accepted audience is the Azure Resource Manager (`https://management.azure.com`),
  because `az` can mint that token without an app registration. That is fine for a toy on your laptop.
  In a real deployment set `AUDIENCES` to your own API. Never accept tokens that were issued for another service.
- The Foundry docs say Agent Service blocks Microsoft audience tokens to custom MCP servers
  (`Cannot pass Microsoft token to untrusted MCP endpoint`). Use your own app registration and an audience you control.
- Agent Service only reaches remote MCP endpoints. To try this server from a Foundry agent, host it on a
  public HTTPS endpoint such as Azure Container Apps. That is not part of this demo.
- The server never logs or returns the token itself.
