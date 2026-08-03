from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BACKEND = "victoriametrics"


@dataclass(frozen=True)
class Settings:
    """How this service talks to the metrics store.

    No credential: the store listens on loopback and FastAPI is the only way in.
    The tokens Datum *accepts* are a different thing and live in `DATUM_TOKENS`,
    read by `TokenStore.from_env`.
    """

    url: str
    backend: str = DEFAULT_BACKEND
    dialect: str = "mysql"
    mode: str = "raw"

    @classmethod
    def from_env(cls) -> Settings:
        url = os.environ.get("DATUM_URL")
        if not url:
            raise RuntimeError("DATUM_URL is not set; point it at the metrics store.")
        return cls(
            url=url,
            backend=os.environ.get("DATUM_BACKEND", DEFAULT_BACKEND),
            dialect=os.environ.get("DATUM_DIALECT", "mysql"),
            mode=os.environ.get("DATUM_MODE", "raw"),
        )
