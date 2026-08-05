from __future__ import annotations

import clickhouse_connect
from clickhouse_connect.driver.exceptions import ClickHouseError, OperationalError

from datum.api.internals.providers.base import MetricProvider, ProviderError, QueryRefused, Rows
from datum.config.clickhouse import COLUMNS, DATABASE, TABLE


class ClickHouseProvider(MetricProvider):
    """Reads are passed through as written; ClickHouse is what refuses a bad one.

    `readonly=1` on every read means a query route cannot mutate even when the
    credential could.
    """

    def __init__(
        self,
        host: str,
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = DATABASE,
        table: str = TABLE,
        statements: tuple[str, ...] = (),
        max_rows: int = 100_000,
        timeout: float = 30.0,
    ):
        self.database = database
        self.table = table
        self.statements = statements
        self.max_rows = max_rows
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

    @property
    def read_settings(self) -> dict:
        return {
            "readonly": 1,
            "max_result_rows": self.max_rows,
            "result_overflow_mode": "break",
            "max_execution_time": int(self.timeout),
        }

    def ensure_schema(self) -> None:
        for statement in self.statements:
            self._run(self.client.command, statement)

    def fetch(self, sql: str) -> Rows:
        result = self._read(sql)
        columns = list(result.column_names)
        rows = [dict(zip(columns, row)) for row in result.result_rows]
        return Rows(columns=columns, rows=rows, truncated=len(rows) >= self.max_rows)

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

    @property
    def metrics(self) -> list[str]:
        sql = f"SELECT DISTINCT metric FROM {self.qualified} ORDER BY metric"
        return [row[0] for row in self._read(sql).result_rows]

    def get_labels(self, metric: str) -> list[str]:
        sql = (
            f"SELECT DISTINCT arrayJoin(mapKeys(labels)) AS label FROM {self.qualified} "
            "WHERE metric = %(metric)s ORDER BY label"
        )
        return [row[0] for row in self._read(sql, {"metric": metric}).result_rows]

    def get_label_values(self, metric: str, label: str) -> list[str]:
        sql = (
            f"SELECT DISTINCT labels[%(label)s] AS value FROM {self.qualified} "
            "WHERE metric = %(metric)s AND has(mapKeys(labels), %(label)s) ORDER BY value"
        )
        return [row[0] for row in self._read(sql, {"metric": metric, "label": label}).result_rows]

    def _read(self, sql: str, parameters: dict | None = None):
        return self._run(self.client.query, sql, parameters=parameters, settings=self.read_settings)

    def _run(self, call, *arguments, **keywords):
        """Unreachable is a 503, refused is a 400. Never a silent empty answer."""
        try:
            return call(*arguments, **keywords)
        except OperationalError as unreachable:
            raise ProviderError(f"ClickHouse is unreachable: {unreachable}") from unreachable
        except ClickHouseError as refused:
            raise QueryRefused(f"ClickHouse refused it: {refused}") from refused
