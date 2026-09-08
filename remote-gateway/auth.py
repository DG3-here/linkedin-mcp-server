from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt

from config import get_settings


class AuthenticationError(Exception):
    """Raised when an access token cannot be authenticated."""


@dataclass(frozen=True)
class AuthenticatedUser:
    subject: str
    claims: dict[str, Any]


class OAuthAuthenticator:
    """Authenticate access tokens issued by this gateway."""

    def __init__(self, settings) -> None:
        self.settings = settings

    def authenticate(
        self,
        authorization_header: str | None,
    ) -> AuthenticatedUser:
        if not authorization_header:
            raise AuthenticationError("Missing Authorization header.")

        if not authorization_header.lower().startswith("bearer "):
            raise AuthenticationError(
                "Authorization header must use Bearer tokens."
            )

        token = authorization_header[7:].strip()

        if not token:
            raise AuthenticationError("Bearer token is empty.")

        try:
            claims = jwt.decode(
                token,
                self.settings.oauth_signing_secret,
                algorithms=["HS256"],
                audience=self.settings.oauth_audience,
                issuer=self.settings.oauth_issuer.rstrip("/"),
                options={
                    "require": [
                        "exp",
                        "iat",
                        "sub",
                    ]
                },
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid access token.") from exc

        subject = claims.get("sub")

        if not isinstance(subject, str) or not subject:
            raise AuthenticationError(
                "Access token has no valid subject."
            )

        return AuthenticatedUser(
            subject=subject,
            claims=claims,
        )


def authenticate_bearer(request) -> dict[str, Any] | None:
    """
    Authenticate the Authorization header from a Starlette request.

    Returns the JWT claims when valid, otherwise None.
    """

    authorization = request.headers.get("authorization")

    if not authorization:
        return None

    try:
        user = OAuthAuthenticator(get_settings()).authenticate(
            authorization
        )
    except AuthenticationError:
        return None

    return user.claims
