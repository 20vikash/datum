from __future__ import annotations

import threading

import clickhouse_connect
from clickhouse_connect.driver.exceptions import ClickHouseError, OperationalError

from datum.api.internals.providers.base import DatumProvider, ProviderError, QueryRefused
from datum.config.api import DATABASE


class ClickHouseProvider(DatumProvider):
    """Writes rows into whichever table the caller names. Nothing here reads them back."""

    def __init__(
        self,
        host: str,
        database: str = DATABASE,
        port: int = 8123,
        username: str = "default",
        password: str = "",
        timeout: float = 30.0,
    ):
        self.database = database
        self.timeout = timeout
        self._connection = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
        }
        self._local = threading.local()
        self._clients: list = []

    @property
    def client(self):
        """One client per worker thread, so concurrent inserts don't share a session."""
        client = getattr(self._local, "client", None)
        if client is None:
            client = clickhouse_connect.get_client(
                **self._connection,
                connect_timeout=self.timeout,
                send_receive_timeout=self.timeout,
            )
            self._local.client = client
            self._clients.append(client)
        return client

    def ping(self) -> bool:
        """Answers False rather than raising: connecting is itself what may fail."""
        try:
            return self.client.ping()
        except ClickHouseError:
            return False

    def close(self) -> None:
        for client in self._clients:
            client.close()
        self._clients.clear()
        self._local = threading.local()

    def insert(self, table: str, rows: list[dict], columns: tuple[str, ...]) -> int:
        if not rows:
            return 0
        data = [[row[column] for column in columns] for row in rows]
        self._run(
            self.client.insert,
            table,
            data,
            column_names=list(columns),
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
