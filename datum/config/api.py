from __future__ import annotations

import os
from dataclasses import dataclass

from datum.config.clickhouse import DATABASE, TABLE, check_identifier
from datum.config.limits import MAX_ROWS, TIMEOUT


@dataclass(frozen=True)
class Settings:
    """How the API reaches ClickHouse. The user needs SELECT and INSERT, nothing more."""

    host: str
    port: int = 8123
    username: str = "default"
    password: str = ""
    database: str = DATABASE
    table: str = TABLE
    max_rows: int = MAX_ROWS
    timeout: float = TIMEOUT

    def __post_init__(self):
        """Checked here, so no construction path puts an unquotable name into SQL."""
        check_identifier(self.database, "DATUM_CLICKHOUSE_DATABASE")
        check_identifier(self.table, "DATUM_CLICKHOUSE_TABLE")
        check_identifier(self.username, "DATUM_CLICKHOUSE_USER")

    @classmethod
    def from_env(cls) -> Settings:
        host = os.environ.get("DATUM_CLICKHOUSE_HOST")
        if not host:
            raise RuntimeError("DATUM_CLICKHOUSE_HOST is not set; point it at ClickHouse.")
        return cls(
            host=host,
            port=int(os.environ.get("DATUM_CLICKHOUSE_PORT", cls.port)),
            username=os.environ.get("DATUM_CLICKHOUSE_USER", cls.username),
            password=os.environ.get("DATUM_CLICKHOUSE_PASSWORD", cls.password),
            database=os.environ.get("DATUM_CLICKHOUSE_DATABASE", cls.database),
            table=os.environ.get("DATUM_CLICKHOUSE_TABLE", cls.table),
            max_rows=int(os.environ.get("DATUM_MAX_ROWS", cls.max_rows)),
            timeout=float(os.environ.get("DATUM_TIMEOUT", cls.timeout)),
        )
