"""Verify Cloudflare Access JWTs at the origin (resource-server side).

Cloudflare Access fronts the service as the OAuth provider; once a user passes
the Access policy, every forwarded request carries a signed JWT in the
``Cf-Access-Jwt-Assertion`` header. This module validates that JWT so the origin
only ever serves Access-authenticated traffic.

Self-contained and parameterised on purpose: it reads no environment and imports
nothing app-specific, so it can be lifted into a shared package unchanged. Its
only dependencies are PyJWT (with crypto) and Starlette.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

ACCESS_JWT_HEADER = "Cf-Access-Jwt-Assertion"
CERTS_PATH = "/cdn-cgi/access/certs"


class SigningKey(Protocol):
    """A resolved signing key (``jwt.PyJWK`` and test fakes both satisfy this)."""

    key: Any


class SigningKeyResolver(Protocol):
    """Resolves a JWT's signing key by its ``kid`` (``jwt.PyJWKClient`` satisfies this)."""

    def get_signing_key_from_jwt(self, token: str) -> SigningKey: ...


def certs_url(team_domain: str) -> str:
    """Return the JWKS endpoint for a Cloudflare Access team domain."""
    return f"{team_domain.rstrip('/')}{CERTS_PATH}"


def verify_access_jwt(
    token: str,
    *,
    jwks_client: SigningKeyResolver,
    expected_aud: str,
    issuer: str,
) -> dict[str, Any]:
    """Return the JWT's claims, or raise ``jwt.InvalidTokenError`` if invalid.

    Checks the RS256 signature against the team JWKS and that ``aud``, ``iss``,
    and ``exp`` all match — Cloudflare signs with rotating keys, so the signing
    key is selected per-token by its ``kid``.
    """
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=expected_aud,
        issuer=issuer,
    )


class CloudflareAccessMiddleware(BaseHTTPMiddleware):
    """Reject requests that don't carry a valid Cloudflare Access JWT."""

    def __init__(self, app: ASGIApp, *, team_domain: str, expected_aud: str) -> None:
        super().__init__(app)
        self._issuer = team_domain.rstrip("/")
        self._expected_aud = expected_aud
        # PyJWKClient fetches and caches the signing keys (keyed by kid).
        self._jwks_client = jwt.PyJWKClient(certs_url(team_domain))

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not self.is_authenticated(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    def is_authenticated(self, request: Request) -> bool:
        """Return whether the request carries a verifiable Access JWT."""
        token = request.headers.get(ACCESS_JWT_HEADER)
        if not token:
            return False
        try:
            verify_access_jwt(
                token,
                jwks_client=self._jwks_client,
                expected_aud=self._expected_aud,
                issuer=self._issuer,
            )
        except jwt.InvalidTokenError:
            return False
        return True
