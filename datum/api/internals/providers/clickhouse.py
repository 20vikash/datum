from __future__ import annotations

import re

import clickhouse_connect
from clickhouse_connect.driver.client import SettingDef
from clickhouse_connect.driver.exceptions import ClickHouseError, OperationalError

from datum.api.internals.providers.base import MetricProvider, ProviderError, QueryRefused, Rows
from datum.config.clickhouse import COLUMNS, DATABASE, RESOURCE_SETTING, TABLE, get_schema

GRANTS = "SHOW GRANTS FOR CURRENT_USER"
GRANTED_ON = re.compile(r"\bON\s+(\S+)")


class ClickHouseProvider(MetricProvider):
    """Reads are passed through as written; ClickHouse is what refuses a bad one.

    `readonly=1` on every read means a query route cannot mutate even when the
    credential could, and it is also what stops a caller resetting the setting
    that scopes them to their own rows.
    """

    def __init__(
        self,
        host: str,
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = DATABASE,
        table: str = TABLE,
        max_rows: int = 100_000,
        timeout: float = 30.0,
    ):
        self.database = database
        self.table = table
        self.username = username
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
            # Registering a custom setting here.
            self._client.server_settings[RESOURCE_SETTING] = SettingDef(RESOURCE_SETTING, "", 0)
        return self._client

    @property
    def qualified(self) -> str:
        return f"{self.database}.{self.table}"

    def get_read_settings(self, resource_id: str) -> dict:
        return {
            "readonly": 1,
            "max_result_rows": self.max_rows,
            "result_overflow_mode": "break",
            "max_execution_time": int(self.timeout),
            RESOURCE_SETTING: resource_id,
        }

    def ensure_schema(self) -> None:
        for statement in get_schema(self.database, self.table, self.username):
            self._run(self.client.command, statement)
        self.check_privileges()

    def check_privileges(self) -> None:
        """Refuse to start on a credential that reaches past its own table."""
        allowed = {self.qualified, f"{self.database}.*"}
        grants = [row[0] for row in self._run(self.client.query, GRANTS).result_rows]
        wider = [line for line in grants if self._granted_on(line) not in allowed]
        if wider:
            raise ProviderError("Unsafe query privileges")

    def fetch(self, sql: str, resource_id: str) -> Rows:
        result = self._read(sql, resource_id)
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

    def get_metrics(self, resource_id: str) -> list[str]:
        sql = f"SELECT DISTINCT metric FROM {self.qualified} ORDER BY metric"
        return [row[0] for row in self._read(sql, resource_id=resource_id).result_rows]

    def get_labels(self, metric: str, resource_id: str) -> list[str]:
        sql = (
            f"SELECT DISTINCT arrayJoin(mapKeys(labels)) AS label FROM {self.qualified} "
            "WHERE metric = %(metric)s ORDER BY label"
        )
        return [
            row[0]
            for row in self._read(
                sql, resource_id=resource_id, parameters={"metric": metric}
            ).result_rows
        ]

    def get_label_values(self, metric: str, label: str, resource_id: str) -> list[str]:
        sql = (
            f"SELECT DISTINCT labels[%(label)s] AS value FROM {self.qualified} "
            "WHERE metric = %(metric)s AND has(mapKeys(labels), %(label)s) ORDER BY value"
        )
        parameters = {"metric": metric, "label": label}
        return [
            row[0]
            for row in self._read(sql, resource_id=resource_id, parameters=parameters).result_rows
        ]

    def _read(self, sql: str, resource_id: str, parameters: dict | None = None):
        settings = self.get_read_settings(resource_id)
        return self._run(self.client.query, sql, parameters=parameters, settings=settings)

    def _granted_on(self, line: str) -> str:
        target = GRANTED_ON.search(line)
        return target.group(1) if target else ""

    def _run(self, call, *arguments, **keywords):
        """Unreachable is a 503, refused is a 400. Never a silent empty answer."""
        try:
            return call(*arguments, **keywords)
        except OperationalError as unreachable:
            raise ProviderError(f"ClickHouse is unreachable: {unreachable}") from unreachable
        except ClickHouseError as refused:
            raise QueryRefused(f"ClickHouse refused it: {refused}") from refused
