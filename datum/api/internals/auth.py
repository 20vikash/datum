from __future__ import annotations

import os
from dataclasses import dataclass, field

import jwt

PUBLIC_KEY_VARIABLE = "DATUM_JWT_PUBLIC_KEY"
ACCESS_CLAIM = "vm_access"
LABELS_CLAIM = "metrics_extra_labels"
ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]


@dataclass(frozen=True)
class Identity:
    """Who a token says the caller is.

    Read side only. Writes go to vmauth, which stamps these same labels from
    the same claim before VictoriaMetrics sees the samples.
    """

    labels: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_claims(cls, claims: dict) -> Identity:
        """`vm_access.metrics_extra_labels` is a list of `name=value` strings."""
        labels = {}
        for entry in claims.get(ACCESS_CLAIM, {}).get(LABELS_CLAIM, []):
            name, _, value = str(entry).partition("=")
            if value:
                labels[name] = value
        return cls(labels=labels)


class TokenVerifier:
    """Verifies the JWTs Central mints, against its public key.

    The same key vmauth is configured with, so a token that can write can also
    read. HMAC is deliberately absent: vmauth verifies with RSA or ECDSA only,
    and the two must not disagree about what a valid token is.
    """

    def __init__(self, public_key: str | None = None):
        self.public_key = (public_key or "").strip()

    @classmethod
    def from_env(cls) -> TokenVerifier:
        """Read `DATUM_JWT_PUBLIC_KEY`. Unset means every /v1 call is a 401."""
        return cls(os.environ.get(PUBLIC_KEY_VARIABLE))

    @property
    def is_configured(self) -> bool:
        return bool(self.public_key)

    def resolve(self, token: str) -> Identity | None:
        """The identity a valid token carries, or None. Never raises."""
        if not self.is_configured:
            return None
        try:
            claims = jwt.decode(token, self.public_key, algorithms=ALGORITHMS)
        except jwt.InvalidTokenError:
            return None
        return Identity.from_claims(claims)
