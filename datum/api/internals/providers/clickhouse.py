from __future__ import annotations

import re

import clickhouse_connect
from clickhouse_connect.driver.exceptions import ClickHouseError, OperationalError

from datum.api.internals.providers.base import (
    LogProvider,
    MetricProvider,
    ProviderError,
    QueryRefused,
)
from datum.config.clickhouse import (
    COLUMNS,
    DATABASE,
    LOG_COLUMNS,
    LOG_TABLE,
    TABLE,
    get_log_schema,
    get_schema,
)

GRANTS = "SHOW GRANTS FOR CURRENT_USER"
GRANTED_ON = re.compile(r"\bON\s+(\S+)")


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
                **self._connection,
                connect_timeout=self.timeout,
                send_receive_timeout=self.timeout,
            )
        return self._client

    @property
    def qualified(self) -> str:
        return f"{self.database}.{self.table}"

    def ensure_schema(self) -> None:
        for statement in get_schema(self.database, self.table):
            self._run(self.client.command, statement)
        self.check_privileges()

    def check_privileges(self) -> None:
        """Refuse to start on a credential that reaches past datum's own tables."""
        allowed = {
            f"{self.database}.{TABLE}",
            f"{self.database}.{LOG_TABLE}",
            f"{self.database}.*",
        }

        grants = [
            row[0]
            for row in self._run(self.client.query, GRANTS).result_rows
        ]
        wider = [
            line for line in grants
            if self._granted_on(line) not in allowed
        ]

        if wider:
            raise ProviderError(
                "Unsafe query privileges:\n" + "\n".join(wider)
            )

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

    def _granted_on(self, line: str) -> str:
        target = GRANTED_ON.search(line)
        return target.group(1) if target else ""

    def _run(self, call, *arguments, **keywords):
        """Unreachable is a 503, refused is a 400. Never a silent success."""
        try:
            return call(*arguments, **keywords)
        except OperationalError as unreachable:
            raise ProviderError(
                f"ClickHouse is unreachable: {unreachable}"
            ) from unreachable
        except ClickHouseError as refused:
            raise QueryRefused(
                f"ClickHouse refused it: {refused}"
            ) from refused


class ClickHouseLogProvider(LogProvider):
    """Writes logs. Nothing here reads them back — readers use ClickHouse directly."""

    def __init__(
        self,
        host: str,
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = DATABASE,
        table: str = LOG_TABLE,
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
                **self._connection,
                connect_timeout=self.timeout,
                send_receive_timeout=self.timeout,
            )
        return self._client

    @property
    def qualified(self) -> str:
        return f"{self.database}.{self.table}"

    def ensure_schema(self) -> None:
        for statement in get_log_schema(self.database, self.table):
            self._run(self.client.command, statement)

    def ingest(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        data = [[row[column] for column in LOG_COLUMNS] for row in rows]

        self._run(
            self.client.insert,
            self.table,
            data,
            column_names=list(LOG_COLUMNS),
            database=self.database,
        )

        return len(rows)

    def _run(self, call, *arguments, **keywords):
        """Unreachable is a 503, refused is a 400. Never a silent success."""
        try:
            return call(*arguments, **keywords)
        except OperationalError as unreachable:
            raise ProviderError(
                f"ClickHouse is unreachable: {unreachable}"
            ) from unreachable
        except ClickHouseError as refused:
            raise QueryRefused(
                f"ClickHouse refused it: {refused}"
            ) from refused