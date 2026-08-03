from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """How this service talks to the metrics store.

    The store URL is the only required setting; everything else mirrors a
    `datum_sql.connect` keyword and is passed straight through.
    """

    url: str
    token: str | None = None
    dialect: str = "mysql"
    mode: str = "raw"

    @classmethod
    def from_env(cls) -> Settings:
        url = os.environ.get("DATUM_URL")
        if not url:
            raise RuntimeError("DATUM_URL is not set; point it at the metrics store.")
        return cls(
            url=url,
            token=os.environ.get("DATUM_TOKEN"),
            dialect=os.environ.get("DATUM_DIALECT", "mysql"),
            mode=os.environ.get("DATUM_MODE", "raw"),
        )
