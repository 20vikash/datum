"""The thing you import: SQL in, rows out."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .client import VictoriaClient
from .planner import DEFAULT_WINDOW, plan
from .spec import QuerySpec

MAX_ROWS = 500_000


@dataclass
class Result:
    columns: list[str]
    rows: list[dict]
    spec: QuerySpec
    truncated: bool = False

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def tuples(self) -> list[tuple]:
        return [tuple(row.get(column) for column in self.columns) for row in self.rows]

    def to_arrow(self):
        import pyarrow as pa

        return pa.Table.from_pylist(
            [{column: row.get(column) for column in self.columns} for row in self.rows]
        )


class Connection:
    """Reads a Prometheus-compatible store using a narrow dialect of SQL.

    Each metric behaves like a table whose columns are its label names plus
    `ts` and `value`. One SELECT becomes one PromQL range query.
    """

    def __init__(
        self,
        url: str,
        token: str | None = None,
        dialect: str = "mysql",
        default_window: timedelta = DEFAULT_WINDOW,
        max_rows: int = MAX_ROWS,
        step: str | None = None,
        mode: str = "raw",
    ):
        self.client = VictoriaClient(url, token=token)
        self.dialect = dialect
        self.default_window = default_window
        self.max_rows = max_rows
        self.step = step
        self.mode = mode

    # ---------- catalog ----------

    def tables(self) -> list[str]:
        return self.client.metrics()

    def columns(self, metric: str) -> list[str]:
        return [*self.client.labels(metric), "ts", "value"]

    def distinct(self, metric: str, label: str) -> list[str]:
        return self.client.label_values(metric, label)

    # ---------- query ----------

    def explain(self, sql: str) -> dict:
        return self._plan(sql).describe()

    def sql(self, sql: str) -> Result:
        spec = self._plan(sql)
        rows = self.client.fetch(spec)

        truncated = False
        if len(rows) > self.max_rows:
            rows = rows[: self.max_rows]
            truncated = True

        if spec.order_by:
            for column, descending in reversed(spec.order_by):
                rows.sort(key=lambda row: (row.get(column) is None, row.get(column)),
                          reverse=descending)

        if spec.limit is not None:
            rows = rows[: spec.limit]

        columns = spec.columns or self._infer_columns(rows)
        if spec.columns:
            rows = [{column: row.get(column) for column in columns} for row in rows]

        return Result(columns=columns, rows=rows, spec=spec, truncated=truncated)

    def _plan(self, sql: str) -> QuerySpec:
        return plan(sql, dialect=self.dialect, step=self.step,
                    default_window=self.default_window, mode=self.mode)

    @staticmethod
    def _infer_columns(rows: list[dict]) -> list[str]:
        seen: list[str] = []
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.append(key)
        tail = [name for name in ("ts", "value") if name in seen]
        return [name for name in seen if name not in tail] + tail


def connect(url: str, token: str | None = None, **options) -> Connection:
    return Connection(url, token=token, **options)
