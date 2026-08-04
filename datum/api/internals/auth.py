from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import jwt

PUBLIC_KEY_FILE_VARIABLE = "DATUM_JWT_PUBLIC_KEY_FILE"
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

    Reads the same PEM `bootstrap.py` points vmauth at, so a token that can
    write can also read and the two can never disagree. HMAC is deliberately
    absent: vmauth verifies with RSA or ECDSA only.
    """

    def __init__(self, public_key: str | None = None):
        self.public_key = (public_key or "").strip()

    @classmethod
    def from_env(cls) -> TokenVerifier:
        """Read the key at `DATUM_JWT_PUBLIC_KEY_FILE`.

        A path that is set but unreadable is a startup failure, never a service
        that silently answers 401 to everyone.
        """
        location = os.environ.get(PUBLIC_KEY_FILE_VARIABLE)
        if not location:
            return cls()
        path = Path(location)
        if not path.is_file():
            raise RuntimeError(f"{PUBLIC_KEY_FILE_VARIABLE} is {location}, which is not a file.")
        return cls(path.read_text())

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
