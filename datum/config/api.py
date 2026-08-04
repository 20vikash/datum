from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """How the API talks to the metrics store.

    No credential: the store listens on loopback, reads come through this
    service and writes come through vmauth. The key callers are verified with is
    a different thing and lives in `DATUM_JWT_PUBLIC_KEY_FILE`, read by
    `TokenVerifier.from_env`. `bootstrap.py` sets both on the unit.
    """

    url: str
    dialect: str = "mysql"
    mode: str = "raw"
    # BI tools paginate tables. Over a relative window that is incoherent, so the
    # page window is dropped and the caller gets the whole window instead.
    ignore_pagination: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        url = os.environ.get("DATUM_URL")
        if not url:
            raise RuntimeError("DATUM_URL is not set; point it at the metrics store.")
        return cls(
            url=url,
            dialect=os.environ.get("DATUM_DIALECT", "mysql"),
            mode=os.environ.get("DATUM_MODE", "raw"),
            ignore_pagination=os.environ.get("DATUM_IGNORE_PAGINATION", "1") != "0",
        )
