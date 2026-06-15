"""Tests for the self-contained Cloudflare Access verifier.

No network: an RSA keypair is generated in-process, tokens are minted with the
private key, and the JWKS client is replaced by a fake that hands back the
matching public key.
"""

import datetime
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import cf_access

TEAM_DOMAIN = "https://example.cloudflareaccess.com"
AUD = "test-aud-tag"


class FakeJWKSClient:
    """A stand-in PyJWKClient that always resolves to the test public key."""

    def __init__(self, public_key: object) -> None:
        self._key = public_key

    def get_signing_key_from_jwt(self, token: str) -> "FakeSigningKey":
        return FakeSigningKey(self._key)


class FakeSigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


@pytest.fixture
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks_client(rsa_key: rsa.RSAPrivateKey) -> FakeJWKSClient:
    return FakeJWKSClient(rsa_key.public_key())


def mint_token(
    rsa_key: rsa.RSAPrivateKey,
    *,
    aud: str = AUD,
    iss: str = TEAM_DOMAIN,
    expired: bool = False,
) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    exp = now - datetime.timedelta(hours=1) if expired else now + datetime.timedelta(hours=1)
    payload = {"aud": aud, "iss": iss, "exp": exp, "sub": "user-123", "email": "me@example.com"}
    return jwt.encode(payload, rsa_key, algorithm="RS256")


def test_verify_returns_claims_for_valid_token(rsa_key: rsa.RSAPrivateKey, jwks_client: FakeJWKSClient) -> None:
    claims = cf_access.verify_access_jwt(
        mint_token(rsa_key), jwks_client=jwks_client, expected_aud=AUD, issuer=TEAM_DOMAIN
    )
    assert claims["sub"] == "user-123"
    assert claims["email"] == "me@example.com"


@pytest.mark.parametrize(
    "token_kwargs",
    [
        pytest.param({"aud": "other-aud"}, id="wrong-aud"),
        pytest.param({"iss": "https://attacker.cloudflareaccess.com"}, id="wrong-iss"),
        pytest.param({"expired": True}, id="expired"),
    ],
)
def test_verify_rejects_bad_token(
    rsa_key: rsa.RSAPrivateKey, jwks_client: FakeJWKSClient, token_kwargs: dict[str, Any]
) -> None:
    with pytest.raises(jwt.InvalidTokenError):
        cf_access.verify_access_jwt(
            mint_token(rsa_key, **token_kwargs),
            jwks_client=jwks_client,
            expected_aud=AUD,
            issuer=TEAM_DOMAIN,
        )


def test_verify_rejects_malformed_token(jwks_client: FakeJWKSClient) -> None:
    with pytest.raises(jwt.InvalidTokenError):
        cf_access.verify_access_jwt("not-a-jwt", jwks_client=jwks_client, expected_aud=AUD, issuer=TEAM_DOMAIN)


@pytest.fixture
def client(rsa_key: rsa.RSAPrivateKey, jwks_client: FakeJWKSClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(cf_access.jwt, "PyJWKClient", lambda _url: jwks_client)
    app = Starlette(routes=[Route("/mcp", lambda _req: PlainTextResponse("ok"))])
    app.add_middleware(cf_access.CloudflareAccessMiddleware, team_domain=TEAM_DOMAIN, expected_aud=AUD)
    return TestClient(app)


def test_middleware_rejects_missing_header(client: TestClient) -> None:
    assert client.get("/mcp").status_code == 401


def test_middleware_accepts_valid_token(client: TestClient, rsa_key: rsa.RSAPrivateKey) -> None:
    response = client.get("/mcp", headers={cf_access.ACCESS_JWT_HEADER: mint_token(rsa_key)})
    assert response.status_code == 200
    assert response.text == "ok"


def test_middleware_rejects_malformed_token(client: TestClient) -> None:
    assert client.get("/mcp", headers={cf_access.ACCESS_JWT_HEADER: "not-a-jwt"}).status_code == 401


def test_middleware_rejects_wrong_aud(client: TestClient, rsa_key: rsa.RSAPrivateKey) -> None:
    token = mint_token(rsa_key, aud="other-aud")
    assert client.get("/mcp", headers={cf_access.ACCESS_JWT_HEADER: token}).status_code == 401
