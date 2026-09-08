from __future__ import annotations

import base64
import hashlib
import html
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import jwt
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import get_settings
from identity.store import IdentityStore


@dataclass
class AuthorizationRequest:
    client_id: str
    redirect_uri: str
    state: str
    code_challenge: str
    scope: str
    resource: str


_pending: dict[str, AuthorizationRequest] = {}
_codes: dict[str, dict] = {}


def _settings():
    return get_settings()


def _store():
    return IdentityStore(_settings().data_dir)


def _sign(payload: dict) -> str:
    return jwt.encode(
        payload,
        _settings().oauth_signing_secret,
        algorithm="HS256",
    )


def _verify(token: str) -> dict:
    return jwt.decode(
        token,
        _settings().oauth_signing_secret,
        algorithms=["HS256"],
        audience=_settings().oauth_audience,
        issuer=_settings().oauth_issuer,
    )


async def protected_resource_metadata(request: Request):
    base = _settings().public_base_url.rstrip("/")
    return JSONResponse(
        {
            "resource": f"{base}{_settings().mcp_path}",
            "authorization_servers": [base],
            "scopes_supported": ["linkedin:read", "linkedin:write"],
            "bearer_methods_supported": ["header"],
        }
    )


async def authorization_server_metadata(request: Request):
    base = _settings().public_base_url.rstrip("/")

    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["linkedin:read", "linkedin:write"],
            "token_endpoint_auth_methods_supported": ["none"],
        }
    )


async def authorize(request: Request):
    query = request.query_params

    required = [
        "client_id",
        "redirect_uri",
        "response_type",
        "state",
        "code_challenge",
    ]

    missing = [key for key in required if not query.get(key)]

    if missing:
        return JSONResponse(
            {"error": "invalid_request", "missing": missing},
            status_code=400,
        )

    if query["response_type"] != "code":
        return JSONResponse(
            {"error": "unsupported_response_type"},
            status_code=400,
        )

    request_id = secrets.token_urlsafe(24)

    _pending[request_id] = AuthorizationRequest(
        client_id=query["client_id"],
        redirect_uri=query["redirect_uri"],
        state=query["state"],
        code_challenge=query["code_challenge"],
        scope=query.get("scope", "linkedin:read"),
        resource=query.get("resource", ""),
    )

    safe_id = html.escape(request_id)

    return HTMLResponse(
        f"""
        <!doctype html>
        <html>
        <head>
          <title>LinkedIn MCP</title>
          <meta name="viewport" content="width=device-width,initial-scale=1">
          <style>
            body {{
              font-family: -apple-system,BlinkMacSystemFont,sans-serif;
              max-width:480px;
              margin:80px auto;
              padding:24px;
            }}
            input {{
              width:100%;
              box-sizing:border-box;
              padding:12px;
              margin:8px 0 16px;
              border:1px solid #ccc;
              border-radius:8px;
            }}
            button {{
              width:100%;
              padding:13px;
              border:0;
              border-radius:8px;
              background:#111;
              color:white;
              font-size:16px;
              cursor:pointer;
            }}
          </style>
        </head>
        <body>
          <h1>Connect LinkedIn MCP</h1>
          <p>Sign in with your recruiter email to authorize Claude.</p>

          <form method="post" action="/oauth/authorize/approve">
            <input type="hidden" name="request_id" value="{safe_id}">

            <label>Email</label>
            <input
              name="email"
              type="email"
              required
              autocomplete="email"
              placeholder="recruiter@company.com"
            >

            <button type="submit">Continue</button>
          </form>
        </body>
        </html>
        """
    )


async def approve_authorization(request: Request):
    form = await request.form()

    request_id = str(form.get("request_id", ""))
    email = str(form.get("email", "")).strip().lower()

    pending = _pending.pop(request_id, None)

    if pending is None:
        return JSONResponse(
            {"error": "invalid_request", "error_description": "Expired authorization request"},
            status_code=400,
        )

    if not email or "@" not in email:
        return JSONResponse(
            {"error": "invalid_request"},
            status_code=400,
        )

    user = _store().get_or_create(email)

    code = secrets.token_urlsafe(32)

    _codes[code] = {
        "client_id": pending.client_id,
        "redirect_uri": pending.redirect_uri,
        "code_challenge": pending.code_challenge,
        "scope": pending.scope,
        "resource": pending.resource,
        "user_id": user.user_id,
        "expires_at": time.time() + 300,
    }

    params = urlencode(
        {
            "code": code,
            "state": pending.state,
        }
    )

    return RedirectResponse(
        f"{pending.redirect_uri}?{params}",
        status_code=302,
    )


async def token(request: Request):
    form = await request.form()

    grant_type = str(form.get("grant_type", ""))
    code = str(form.get("code", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    client_id = str(form.get("client_id", ""))
    verifier = str(form.get("code_verifier", ""))

    if grant_type != "authorization_code":
        return JSONResponse(
            {"error": "unsupported_grant_type"},
            status_code=400,
        )

    stored = _codes.pop(code, None)

    if stored is None or stored["expires_at"] < time.time():
        return JSONResponse(
            {"error": "invalid_grant"},
            status_code=400,
        )

    if stored["client_id"] != client_id:
        return JSONResponse(
            {"error": "invalid_grant"},
            status_code=400,
        )

    if stored["redirect_uri"] != redirect_uri:
        return JSONResponse(
            {"error": "invalid_grant"},
            status_code=400,
        )

    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    if not verifier or not secrets.compare_digest(
        challenge,
        stored["code_challenge"],
    ):
        return JSONResponse(
            {"error": "invalid_grant"},
            status_code=400,
        )

    now = int(time.time())

    token = _sign(
        {
            "iss": _settings().oauth_issuer,
            "sub": stored["user_id"],
            "aud": _settings().oauth_audience,
            "scope": stored["scope"],
            "resource": stored["resource"],
            "iat": now,
            "exp": now + 3600,
            "jti": secrets.token_urlsafe(16),
        }
    )

    return JSONResponse(
        {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": stored["scope"],
        }
    )


def authenticate_bearer(request: Request) -> dict | None:
    authorization = request.headers.get("authorization", "")

    if not authorization.startswith("Bearer "):
        return None

    token = authorization[7:].strip()

    try:
        return _verify(token)
    except jwt.PyJWTError:
        return None
