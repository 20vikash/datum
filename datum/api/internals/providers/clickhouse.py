from __future__ import annotations

import clickhouse_connect
from clickhouse_connect.driver.exceptions import ClickHouseError, OperationalError

from datum.api.internals.providers.base import MetricProvider, ProviderError, QueryRefused
from datum.config.clickhouse import COLUMNS, DATABASE, TABLE, get_schema


class ClickHouseProvider(MetricProvider):
    """Writes samples. Nothing here reads them back — Insights does that directly."""

    def __init__(
        self,
        host: str,
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = DATABASE,
        table: str = TABLE,
        timeout: float = 30.0,
    ):
        self.database = database
        self.table = table
        self.timeout = timeout
        self._connection = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
        }
        self._client = None

    @property
    def client(self):
        """Connected on first use, so building the provider opens no socket."""
        if self._client is None:
            self._client = clickhouse_connect.get_client(
                **self._connection, connect_timeout=self.timeout, send_receive_timeout=self.timeout
            )
        return self._client

    @property
    def qualified(self) -> str:
        return f"{self.database}.{self.table}"

    def ensure_schema(self) -> None:
        for statement in get_schema(self.database, self.table):
            self._run(self.client.command, statement)

    def ingest(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        data = [[row[column] for column in COLUMNS] for row in rows]
        self._run(
            self.client.insert,
            self.table,
            data,
            column_names=list(COLUMNS),
            database=self.database,
        )
        return len(rows)

    def _run(self, call, *arguments, **keywords):
        """Unreachable is a 503, refused is a 400. Never a silent success."""
        try:
            return call(*arguments, **keywords)
        except OperationalError as unreachable:
            raise ProviderError(f"ClickHouse is unreachable: {unreachable}") from unreachable
        except ClickHouseError as refused:
            raise QueryRefused(f"ClickHouse refused it: {refused}") from refused
