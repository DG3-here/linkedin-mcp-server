from __future__ import annotations

import os

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from config import get_settings
from oauth import (
    authenticate_bearer,
    authorization_server_metadata,
    authorize,
    approve_authorization,
    protected_resource_metadata,
    token,
)


settings = get_settings()


async def health(request: Request):
    return JSONResponse(
        {
            "status": "ok",
            "service": "linkedin-mcp",
            "environment": settings.app_env,
        }
    )


async def ready(request: Request):
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                settings.mcp_upstream_url.replace("/mcp", "/"),
            )

        upstream_ok = response.status_code < 500
    except Exception:
        upstream_ok = False

    return JSONResponse(
        {
            "status": "ready" if upstream_ok else "degraded",
            "upstream": upstream_ok,
        },
        status_code=200 if upstream_ok else 503,
    )


async def mcp(request: Request):
    claims = authenticate_bearer(request)

    if claims is None:
        base = settings.public_base_url.rstrip("/")

        return Response(
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource", '
                    'scope="linkedin:read"'
                )
            },
        )

    user_id = claims.get("sub")

    if not user_id:
        return JSONResponse(
            {"error": "invalid_token"},
            status_code=401,
        )

    # Identity is intentionally forwarded separately from the OAuth token.
    # The upstream MCP must never receive the external bearer token.
    headers = {
        "content-type": request.headers.get(
            "content-type",
            "application/json",
        ),
        "accept": request.headers.get(
            "accept",
            "application/json, text/event-stream",
        ),
        "x-authenticated-user": user_id,
    }

    for name in (
        "mcp-session-id",
        "last-event-id",
        "mcp-protocol-version",
    ):
        value = request.headers.get(name)
        if value:
            headers[name] = value

    body = await request.body()

    async with httpx.AsyncClient(timeout=None) as client:
        upstream = await client.request(
            request.method,
            settings.mcp_upstream_url,
            content=body,
            headers=headers,
        )

    response_headers = {}

    for name in (
        "content-type",
        "cache-control",
        "mcp-session-id",
        "mcp-protocol-version",
    ):
        value = upstream.headers.get(name)
        if value:
            response_headers[name] = value

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


async def oauth_user(request: Request):
    claims = authenticate_bearer(request)

    if claims is None:
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
        )

    return JSONResponse(
        {
            "user_id": claims["sub"],
            "scope": claims.get("scope", ""),
        }
    )


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/ready", ready, methods=["GET"]),

    Route(
        "/.well-known/oauth-protected-resource",
        protected_resource_metadata,
        methods=["GET"],
    ),
    Route(
        "/.well-known/oauth-authorization-server",
        authorization_server_metadata,
        methods=["GET"],
    ),

    Route("/oauth/authorize", authorize, methods=["GET"]),
    Route(
        "/oauth/authorize/approve",
        approve_authorization,
        methods=["POST"],
    ),
    Route("/oauth/token", token, methods=["POST"]),

    Route("/oauth/user", oauth_user, methods=["GET"]),

    Route("/mcp", mcp, methods=["GET", "POST", "DELETE"]),
]


app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=settings.host,
        port=int(os.environ.get("PORT", settings.port)),
    )
