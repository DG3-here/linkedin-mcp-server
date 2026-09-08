from dataclasses import dataclass
from typing import Any

import jwt

from config import Settings


class AuthenticationError(Exception):
    """Raised when an incoming access token cannot be authenticated."""


@dataclass(frozen=True)
class AuthenticatedUser:
    subject: str
    claims: dict[str, Any]


class OAuthAuthenticator:
    """
    Validates OAuth/OIDC JWT access tokens.

    Development mode deliberately permits localhost-only requests without
    authentication so the gateway can be tested before deployment.

    Production mode requires:
      - OAUTH_ISSUER_URL
      - OAUTH_AUDIENCE
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks_client: jwt.PyJWKClient | None = None

        if settings.oauth_issuer_url:
            jwks_url = settings.oauth_issuer_url.rstrip("/") + "/.well-known/jwks.json"
            self._jwks_client = jwt.PyJWKClient(jwks_url)

    async def authenticate(
        self,
        authorization_header: str | None,
    ) -> AuthenticatedUser:
        if not self.settings.is_production:
            return self._development_user(authorization_header)

        if not self.settings.oauth_issuer_url:
            raise AuthenticationError(
                "OAUTH_ISSUER_URL must be configured in production."
            )

        if not authorization_header:
            raise AuthenticationError("Missing Authorization header.")

        if not authorization_header.lower().startswith("bearer "):
            raise AuthenticationError("Authorization header must use Bearer tokens.")

        token = authorization_header[7:].strip()

        if not token:
            raise AuthenticationError("Bearer token is empty.")

        if self._jwks_client is None:
            raise AuthenticationError("OAuth JWKS client is not configured.")

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)

            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.settings.oauth_audience,
                issuer=self.settings.oauth_issuer_url.rstrip("/"),
                options={
                    "require": ["exp", "iat", "sub"],
                },
            )
        except Exception as exc:
            raise AuthenticationError("Invalid access token.") from exc

        subject = claims.get("sub")

        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("Access token has no valid subject.")

        return AuthenticatedUser(
            subject=subject,
            claims=claims,
        )

    @staticmethod
    def _development_user(
        authorization_header: str | None,
    ) -> AuthenticatedUser:
        if authorization_header:
            return AuthenticatedUser(
                subject="development-user",
                claims={"mode": "development"},
            )

        return AuthenticatedUser(
            subject="development-user",
            claims={"mode": "development"},
        )
