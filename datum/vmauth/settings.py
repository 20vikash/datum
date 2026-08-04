from __future__ import annotations

import os
from dataclasses import dataclass

from datum.api.internals.auth import PUBLIC_KEY_VARIABLE

ISSUER_VARIABLE = "DATUM_OIDC_ISSUER"
SKIP_VERIFY_VARIABLE = "DATUM_JWT_SKIP_VERIFY"

DEFAULT_LISTEN = "127.0.0.1:8427"

# What a producer may reach. Query paths are deliberately absent: a token that
# can write must not be able to read every tenant's series.
WRITE_PATHS = ("/api/v1/write", "/api/v1/import")


@dataclass(frozen=True)
class VmauthSettings:
    """How vmauth verifies producers and where it sends them.

    One of `oidc_issuer`, `public_key` or `skip_verify` decides verification,
    in that order. They are mutually exclusive in vmauth's own config, so
    picking more than one here is a startup failure rather than a silent choice.
    """

    victoria_url: str
    listen: str = DEFAULT_LISTEN
    public_key: str = ""
    oidc_issuer: str = ""
    skip_verify: bool = False
    write_paths: tuple[str, ...] = WRITE_PATHS

    @classmethod
    def from_env(cls, victoria_url: str | None = None) -> VmauthSettings:
        url = victoria_url or os.environ.get("DATUM_URL")
        if not url:
            raise RuntimeError("DATUM_URL is not set; point it at the metrics store.")
        return cls(
            victoria_url=url,
            listen=os.environ.get("DATUM_VMAUTH_LISTEN", DEFAULT_LISTEN),
            public_key=os.environ.get(PUBLIC_KEY_VARIABLE, ""),
            oidc_issuer=os.environ.get(ISSUER_VARIABLE, ""),
            skip_verify=os.environ.get(SKIP_VERIFY_VARIABLE, "0") == "1",
        )

    @property
    def mode(self) -> str:
        """Which verification vmauth will do. Raises rather than guessing."""
        chosen = [
            name
            for name, picked in (
                ("oidc", bool(self.oidc_issuer)),
                ("public_key", bool(self.public_key.strip())),
                ("skip_verify", self.skip_verify),
            )
            if picked
        ]
        if not chosen:
            raise RuntimeError(
                f"No JWT verification configured. Set {PUBLIC_KEY_VARIABLE}, "
                f"{ISSUER_VARIABLE}, or {SKIP_VERIFY_VARIABLE}=1 for local testing."
            )
        if len(chosen) > 1:
            raise RuntimeError(
                f"{' and '.join(chosen)} are both set, and vmauth accepts one. "
                "Unset the one you are migrating away from."
            )
        return chosen[0]

    @property
    def is_verifying(self) -> bool:
        """False only when signatures are not checked at all."""
        return self.mode != "skip_verify"
