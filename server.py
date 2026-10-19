"""Tiny MCP server with one tool: whoami.

The tool answers a single question: "Who does this server see in the bearer token?"
That is exactly the difference between the MCP authentication methods in Microsoft Foundry:

* Microsoft Entra with agent identity or project managed identity: the token names an
  application (a workload), no person. User context does not persist.
* OAuth identity passthrough: the token names the signed in person. User context persists.

The server validates real Microsoft Entra access tokens: signature (JWKS of your tenant),
issuer, audience and expiry. It never logs or returns the token itself.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import jwt
from jwt import PyJWKClient
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    audiences: list[str]
    public_url: str = "http://localhost:8000/mcp"
    mask_identifiers: bool = True
    jwks_uri: str | None = None
    allowed_hosts: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Settings":
        tenant_id = os.environ.get("TENANT_ID", "").strip()
        audiences = [a.strip() for a in os.environ.get("AUDIENCES", "").split(",") if a.strip()]
        if not tenant_id or not audiences:
            raise RuntimeError("Set TENANT_ID and AUDIENCES (comma separated). See README.md.")
        return cls(
            tenant_id=tenant_id,
            audiences=audiences,
            public_url=os.environ.get("PUBLIC_URL", cls.public_url),
            mask_identifiers=os.environ.get("MASK_IDENTIFIERS", "true").lower() != "false",
            jwks_uri=os.environ.get("JWKS_URI") or None,
            allowed_hosts=[h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()],
        )


class EntraTokenVerifier:
    """Validates Microsoft Entra access tokens (v1 and v2 issuer formats)."""

    def __init__(self, settings: Settings, jwks_client: Any | None = None) -> None:
        tenant = settings.tenant_id
        self._audiences = settings.audiences
        self._issuers = [
            f"https://login.microsoftonline.com/{tenant}/v2.0",
            f"https://sts.windows.net/{tenant}/",
        ]
        self._jwks = jwks_client or PyJWKClient(
            settings.jwks_uri or f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
            cache_keys=True,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            # PyJWKClient does blocking network IO, so keep it off the event loop.
            signing_key = await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audiences,
                issuer=self._issuers,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError:
            return None

        scopes = str(claims.get("scp", "")).split() + list(claims.get("roles", []))
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("appid") or ""),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            subject=str(claims.get("oid") or claims.get("sub") or ""),
            claims=claims,
        )


_GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


def _mask_guids(value: Any) -> Any:
    """Shorten every GUID inside a string or list, for example the tenant in the issuer URL."""
    if isinstance(value, str):
        return _GUID.sub(lambda m: f"{m.group(0)[:8]}...", value)
    if isinstance(value, list):
        return [_mask_guids(v) for v in value]
    return value


def _mask_id(value: str | None) -> str | None:
    return f"{value[:8]}..." if value else None


def _mask_name(value: str | None) -> str | None:
    if not value:
        return None
    local, _, domain = value.partition("@")
    return f"{local[:1]}***@{domain}" if domain else f"{local[:1]}***"


def describe_caller(claims: dict[str, Any], mask: bool = True) -> dict[str, Any]:
    """Turn the validated token claims into a small, readable answer."""
    user_name = claims.get("upn") or claims.get("preferred_username") or claims.get("unique_name")
    is_user = bool(claims.get("scp") or user_name)

    ident = _mask_id if mask else (lambda v: v)
    name = _mask_name if mask else (lambda v: v)
    guids = _mask_guids if mask else (lambda v: v)

    result: dict[str, Any] = {
        "callerType": "user" if is_user else "application",
        "meaning": (
            "A person is in the token. The server can apply that user's own permissions. "
            "This is what OAuth identity passthrough gives you."
            if is_user
            else "No person in the token, only a workload identity. The server cannot tell which user "
            "triggered the call. This is the situation with Microsoft Entra authentication using the agent "
            "identity or the project managed identity, and with key based authentication."
        ),
        "objectId": ident(claims.get("oid")),
        "tenantId": ident(claims.get("tid")),
        "clientApp": ident(claims.get("azp") or claims.get("appid")),
        "userName": name(user_name) if is_user else None,
        "delegatedScopes": str(claims.get("scp", "")).split() or None,
        "appRoles": claims.get("roles") or None,
        "audience": guids(claims.get("aud")),
        "issuer": guids(claims.get("iss")),
        "expiresAt": datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc).isoformat(),
    }
    return {k: v for k, v in result.items() if v is not None}


def create_app(settings: Settings | None = None, verifier: EntraTokenVerifier | None = None) -> Starlette:
    settings = settings or Settings.from_env()
    verifier = verifier or EntraTokenVerifier(settings)

    mcp = MCPServer(
        "whoami",
        instructions="Call whoami to see which identity this server sees in your bearer token.",
        auth=AuthSettings(
            issuer_url=f"https://login.microsoftonline.com/{settings.tenant_id}/v2.0",
            resource_server_url=settings.public_url,
            # The verifier already checks the audience, so skip the RFC 8707 resource check.
            validate_token_resource=False,
        ),
        token_verifier=verifier,
    )

    @mcp.tool()
    def whoami() -> dict[str, Any]:
        """Tell the caller which identity this server sees in the bearer token."""
        access = get_access_token()
        return describe_caller(access.claims or {}, mask=settings.mask_identifiers) if access else {}

    security = (
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=[],
        )
        if settings.allowed_hosts
        else None
    )
    app = mcp.streamable_http_app(json_response=True, stateless_http=True, transport_security=security)

    async def healthz(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app.router.routes.append(Route("/healthz", healthz))
    return app
