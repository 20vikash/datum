from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

TOKENS_VARIABLE = "DATUM_TOKENS"


class LabelConflict(ValueError):
    """A producer sent a label its own token already fixes."""


@dataclass(frozen=True)
class Identity:
    """Who a token says the caller is.

    `labels` are the producer's fixed labels. Nothing here ever comes from a
    request body.
    """

    tenant: str
    source: str
    labels: dict[str, str] = field(default_factory=dict)

    def stamp(self, labels: dict[str, str]) -> dict[str, str]:
        """Fixed labels win. Claiming one is a refusal, not a silent override."""
        claimed = labels.keys() & self.labels.keys()
        if claimed:
            raise LabelConflict(f"{sorted(claimed)} come from the token, not the body")
        return {**labels, **self.labels, "tenant_id": self.tenant, "source_id": self.source}


class TokenStore:
    """sha256(token) to Identity. Central mints them; Datum only ever checks.

    POC. Held in memory, so it does not survive a restart, and there is no
    Central sync or expiry yet: it is whatever `create_app` was handed. Real
    tokens are expected to be JWTs verified against Central's JWKS, which
    replaces this class rather than extending it -- everything downstream only
    needs `resolve(token) -> Identity | None`.
    """

    def __init__(self, tokens: dict[str, Identity] | None = None):
        self._by_hash: dict[str, Identity] = {}
        for token, identity in (tokens or {}).items():
            self.add(token, identity)

    @classmethod
    def from_env(cls) -> TokenStore:
        """Read `DATUM_TOKENS`: a JSON object of accepted token to identity.

            {"secret": {"tenant": "acme", "source": "pilot_1", "labels": {"region": "ap"}}}

        Unset means no tokens, so every /v1 call is a 401. Malformed is a
        startup failure, never a silently empty store.
        """
        raw = os.environ.get(TOKENS_VARIABLE)
        if not raw or not raw.strip():
            return cls()

        try:
            entries = json.loads(raw)
            return cls({token: Identity(**record) for token, record in entries.items()})
        except (json.JSONDecodeError, AttributeError, TypeError) as malformed:
            raise RuntimeError(f"{TOKENS_VARIABLE} is malformed: {malformed}") from malformed

    def add(self, token: str, identity: Identity) -> None:
        self._by_hash[self.digest(token)] = identity

    def revoke(self, token: str) -> None:
        self._by_hash.pop(self.digest(token), None)

    def resolve(self, token: str) -> Identity | None:
        return self._by_hash.get(self.digest(token))

    @property
    def count(self) -> int:
        return len(self._by_hash)

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
