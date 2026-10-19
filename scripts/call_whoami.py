#!/usr/bin/env python3
"""Call the whoami tool and print what the server sees.

    uv run scripts/call_whoami.py user   # token of the account you are signed in with in az
    uv run scripts/call_whoami.py app    # client credentials of a service principal

For the app mode set AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET.
Set BEARER_TOKEN to send a token you already have. The token is never printed.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ.get("MCP_URL", "http://localhost:8000/mcp")
RESOURCE = os.environ.get("TOKEN_RESOURCE", "https://management.azure.com")


def user_token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", RESOURCE, "--query", "accessToken", "-o", "tsv"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def app_token() -> str:
    form = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": os.environ["AZURE_CLIENT_ID"],
            "client_secret": os.environ["AZURE_CLIENT_SECRET"],
            "scope": f"{RESOURCE}/.default",
        }
    ).encode()
    url = f"https://login.microsoftonline.com/{os.environ['AZURE_TENANT_ID']}/oauth2/v2.0/token"
    with urllib.request.urlopen(urllib.request.Request(url, data=form)) as response:
        return json.load(response)["access_token"]


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "user"
    if mode not in ("user", "app"):
        print(__doc__)
        return 2
    bearer = os.environ.get("BEARER_TOKEN") or (user_token() if mode == "user" else app_token())

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}}
    request = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            reply = json.load(response)
    except urllib.error.HTTPError as error:
        print(f"HTTP {error.code}: {error.read().decode()[:300]}")
        return 1

    result = reply["result"]
    print(json.dumps(result.get("structuredContent") or json.loads(result["content"][0]["text"]), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
