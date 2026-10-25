"""Tests with locally signed tokens, so they need no tenant and no network."""

import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from server import EntraTokenVerifier, Settings, create_app, describe_caller

TENANT = "11111111-2222-3333-4444-555555555555"
AUDIENCE = "api://whoami-demo"
OBJECT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    def __init__(self, key):
        self._public = key.public_key()

    def get_signing_key_from_jwt(self, _token):
        return SimpleNamespace(key=self._public)


def make_client(key, mask=True, required_role=None):
    settings = Settings(tenant_id=TENANT, audiences=[AUDIENCE], mask_identifiers=mask, required_role=required_role)
    verifier = EntraTokenVerifier(settings, jwks_client=FakeJwks(key))
    return TestClient(create_app(settings, verifier), base_url="http://localhost:8000")


def token(key, **overrides):
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": AUDIENCE,
        "exp": int(time.time()) + 600,
        "tid": TENANT,
        "oid": OBJECT_ID,
        "azp": "99999999-8888-7777-6666-555555555555",
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


USER = {"scp": "access_as_user", "preferred_username": "jane.doe@contoso.com"}
APP = {"idtyp": "app", "roles": ["Tools.Run"]}

CALL = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}}
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def call_whoami(client, bearer):
    headers = dict(HEADERS)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return client.post("/mcp", headers=headers, content=json.dumps(CALL))


def payload(response):
    result = response.json()["result"]
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


def test_health_needs_no_token(key):
    with make_client(key) as client:
        assert client.get("/healthz").text == "ok"


def test_no_token_is_rejected(key):
    with make_client(key) as client:
        response = call_whoami(client, None)
        assert response.status_code == 401
        assert "Bearer" in response.headers["www-authenticate"]


def test_garbage_token_is_rejected(key):
    with make_client(key) as client:
        assert call_whoami(client, "not-a-jwt").status_code == 401


@pytest.mark.parametrize(
    "override",
    [
        {"aud": "api://somebody-else"},
        {"iss": "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000000/v2.0"},
        {"exp": int(time.time()) - 60},
    ],
    ids=["wrong-audience", "wrong-tenant", "expired"],
)
def test_invalid_tokens_are_rejected(key, override):
    with make_client(key) as client:
        assert call_whoami(client, token(key, **USER, **override)).status_code == 401


def test_token_signed_by_another_key_is_rejected(key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with make_client(key) as client:
        assert call_whoami(client, token(other, **USER)).status_code == 401


def test_user_token_is_seen_as_user(key):
    with make_client(key) as client:
        body = payload(call_whoami(client, token(key, **USER)))
    assert body["callerType"] == "user"
    assert body["userName"] == "j***@contoso.com"
    assert body["objectId"] == "aaaaaaaa..."
    assert body["delegatedScopes"] == ["access_as_user"]
    assert "appRoles" not in body


def test_app_token_is_seen_as_application(key):
    with make_client(key) as client:
        body = payload(call_whoami(client, token(key, **APP)))
    assert body["callerType"] == "application"
    assert "userName" not in body
    assert body["appRoles"] == ["Tools.Run"]


def test_required_role_missing_is_forbidden(key):
    with make_client(key, required_role="Tools.Run") as client:
        response = call_whoami(client, token(key, idtyp="app"))
    assert response.status_code == 403
    assert "insufficient_scope" in response.text


def test_required_role_present_is_allowed(key):
    with make_client(key, required_role="Tools.Run") as client:
        body = payload(call_whoami(client, token(key, **APP)))
    assert body["appRoles"] == ["Tools.Run"]


def test_v1_issuer_is_accepted(key):
    with make_client(key) as client:
        bearer = token(key, iss=f"https://sts.windows.net/{TENANT}/", **USER)
        assert call_whoami(client, bearer).status_code == 200


def test_masking_can_be_switched_off(key):
    with make_client(key, mask=False) as client:
        body = payload(call_whoami(client, token(key, **USER)))
    assert body["objectId"] == OBJECT_ID
    assert body["userName"] == "jane.doe@contoso.com"


def test_describe_caller_has_no_token_field():
    assert "token" not in describe_caller({"exp": 1, "oid": "x", "scp": "a"})


def test_keys_are_fetched_over_http_with_kid(key):
    """Uses the real PyJWKClient against a local JWKS endpoint, like Entra would serve it."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from jwt.algorithms import RSAAlgorithm

    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "test-kid", "use": "sig", "alg": "RS256"})
    jwks = json.dumps({"keys": [jwk]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(jwks)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        settings = Settings(
            tenant_id=TENANT,
            audiences=[AUDIENCE],
            jwks_uri=f"http://127.0.0.1:{server.server_port}/keys",
        )
        bearer = jwt.encode(
            {
                "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
                "aud": AUDIENCE,
                "exp": int(time.time()) + 600,
                "oid": OBJECT_ID,
                "scp": "access_as_user",
            },
            key,
            algorithm="RS256",
            headers={"kid": "test-kid"},
        )
        with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
            assert payload(call_whoami(client, bearer))["callerType"] == "user"
    finally:
        server.shutdown()


def test_masking_hides_guids_in_issuer_and_audience():
    claims = {
        "exp": 1,
        "scp": "a",
        "oid": OBJECT_ID,
        "tid": TENANT,
        "iss": f"https://sts.windows.net/{TENANT}/",
        "aud": f"api://{OBJECT_ID}",
    }
    text = json.dumps(describe_caller(claims, mask=True))
    assert TENANT not in text
    assert OBJECT_ID not in text
    assert "https://sts.windows.net/11111111.../" in text
