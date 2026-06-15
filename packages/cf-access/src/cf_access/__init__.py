import jwt as jwt  # re-exported as cf_access.jwt so callers/tests can patch PyJWKClient

from cf_access.access import (
    ACCESS_JWT_HEADER,
    CERTS_PATH,
    CloudflareAccessMiddleware,
    SigningKey,
    SigningKeyResolver,
    certs_url,
    verify_access_jwt,
)

__all__ = [
    "ACCESS_JWT_HEADER",
    "CERTS_PATH",
    "CloudflareAccessMiddleware",
    "SigningKey",
    "SigningKeyResolver",
    "certs_url",
    "verify_access_jwt",
]
