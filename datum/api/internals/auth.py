from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import jwt

PUBLIC_KEY_FILE_VARIABLE = "DATUM_JWT_PUBLIC_KEY_FILE"
ISSUER_VARIABLE = "DATUM_OIDC_ISSUER"

ACCESS_CLAIM = "vm_access"
LABELS_CLAIM = "metrics_extra_labels"
ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

DISCOVERY_PATH = "/.well-known/openid-configuration"
# vmauth refreshes its key set every five minutes. Matching it keeps the two
# from disagreeing about a rotated key for longer than they have to.
KEY_LIFESPAN = 300
DISCOVERY_TIMEOUT = 5.0


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
    """Verifies the JWTs Central mints, the same way vmauth does.

    Either a public key on disk or an OIDC issuer to fetch one from -- the two
    modes `bootstrap.py` offers, so reads and writes are configured together.
    HMAC is deliberately absent: vmauth verifies with RSA or ECDSA only.
    """

    def __init__(self, public_key: str | None = None, oidc_issuer: str | None = None):
        self.public_key = (public_key or "").strip()
        self.oidc_issuer = (oidc_issuer or "").strip().rstrip("/")
        self._keys: jwt.PyJWKClient | None = None

    @classmethod
    def from_env(cls) -> TokenVerifier:
        """Read the key file or the issuer `bootstrap.py` put on the unit.

        A key path that is set but unreadable is a startup failure, never a
        service that silently answers 401 to everyone.
        """
        location = os.environ.get(PUBLIC_KEY_FILE_VARIABLE)
        issuer = os.environ.get(ISSUER_VARIABLE)
        if not location:
            return cls(oidc_issuer=issuer)

        path = Path(location)
        if not path.is_file():
            raise RuntimeError(f"{PUBLIC_KEY_FILE_VARIABLE} is {location}, which is not a file.")
        return cls(public_key=path.read_text(), oidc_issuer=issuer)

    @property
    def is_configured(self) -> bool:
        return bool(self.public_key or self.oidc_issuer)

    def resolve(self, token: str) -> Identity | None:
        """The identity a valid token carries, or None. Never raises."""
        if not self.is_configured:
            return None
        try:
            claims = self._decode(token)
        except (jwt.InvalidTokenError, jwt.PyJWKClientError):
            return None
        return Identity.from_claims(claims)

    def _decode(self, token: str) -> dict:
        if not self.oidc_issuer:
            return jwt.decode(token, self.public_key, algorithms=ALGORITHMS)
        signing_key = self._signing_key(token)
        return jwt.decode(token, signing_key, algorithms=ALGORITHMS, issuer=self.oidc_issuer)

    def _signing_key(self, token: str):
        """The key the token's `kid` names, from the issuer's JWKS."""
        if self._keys is None:
            self._keys = jwt.PyJWKClient(self._jwks_uri(), lifespan=KEY_LIFESPAN)
        return self._keys.get_signing_key_from_jwt(token).key

    def _jwks_uri(self) -> str:
        """Discovery, the same two steps vmauth takes.

        Failure raises `PyJWKClientError`, so `resolve` answers 401 while the
        provider is down rather than serving reads with no key at all.
        """
        url = f"{self.oidc_issuer}{DISCOVERY_PATH}"
        try:
            with urllib.request.urlopen(url, timeout=DISCOVERY_TIMEOUT) as response:
                document = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as unreachable:
            raise jwt.PyJWKClientError(f"{url} could not be read: {unreachable}") from unreachable

        uri = document.get("jwks_uri")
        if not uri:
            raise jwt.PyJWKClientError(f"{url} carries no jwks_uri")
        return uri
