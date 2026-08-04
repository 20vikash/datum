from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_LISTEN = "127.0.0.1:8427"

# What a producer may reach. Query paths are deliberately absent: a token that
# can write must not be able to read every tenant's series.
WRITE_PATHS = ("/api/v1/write", "/api/v1/import")

PUBLIC_KEY = "public_key"
OIDC = "oidc"
SKIP_VERIFY = "skip_verify"


@dataclass(frozen=True)
class VmauthSettings:
    """How vmauth verifies producers and where it sends them.

    The key is a path, not its text: vmauth reads the file itself, and Datum
    reads the same one, so the two can never drift apart.
    """

    victoria_url: str
    listen: str = DEFAULT_LISTEN
    public_key_path: Path | None = None
    oidc_issuer: str = ""
    skip_verify: bool = False
    write_paths: tuple[str, ...] = WRITE_PATHS

    @property
    def mode(self) -> str:
        """Which verification vmauth will do. Raises rather than guessing."""
        chosen = [
            name
            for name, picked in (
                (OIDC, bool(self.oidc_issuer)),
                (PUBLIC_KEY, self.public_key_path is not None),
                (SKIP_VERIFY, self.skip_verify),
            )
            if picked
        ]
        if not chosen:
            raise RuntimeError(
                "No JWT verification configured. Pass --public-key, --oidc-issuer, "
                "or --skip-verify for local testing."
            )
        if len(chosen) > 1:
            raise RuntimeError(
                f"{' and '.join(chosen)} are both set, and vmauth accepts one. "
                "Drop the one you are migrating away from."
            )
        return chosen[0]

    @property
    def is_verifying(self) -> bool:
        """False only when signatures are not checked at all."""
        return self.mode != SKIP_VERIFY
