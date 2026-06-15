# cf-access

Cloudflare Access JWT validation middleware for Starlette/MCP origins. Validates
the `Cf-Access-Jwt-Assertion` header Cloudflare injects after a request passes the
Access policy, so the origin only ever serves Access-authenticated traffic.

## Install

```bash
pip install cf-access --index-url https://pypi.ocampor.com/simple/
```

## Quick start

```python
from starlette.applications import Starlette
from cf_access import CloudflareAccessMiddleware

app = Starlette(routes=[...])
app.add_middleware(
    CloudflareAccessMiddleware,
    team_domain="https://<team>.cloudflareaccess.com",
    expected_aud="<application-audience-tag>",
)
```

Requests without a valid Access JWT get a `401`. The middleware fetches and caches
the team's rotating signing keys from the JWKS endpoint, selecting the right key
per token by its `kid`.

## API

- `CloudflareAccessMiddleware(app, *, team_domain, expected_aud)` — Starlette
  middleware that rejects unauthenticated requests.
- `verify_access_jwt(token, *, jwks_client, expected_aud, issuer) -> dict` —
  verify a token and return its claims, or raise `jwt.InvalidTokenError`.
- `certs_url(team_domain) -> str` — the JWKS endpoint for a team domain.
- `SigningKey`, `SigningKeyResolver` — Protocols satisfied by `jwt.PyJWK` /
  `jwt.PyJWKClient`.
