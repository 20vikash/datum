from __future__ import annotations

from dataclasses import dataclass

from datum_sql.spec import QuerySpec

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


def shape(rows: list[dict], spec: QuerySpec, max_rows: int = MAX_ROWS) -> Result:
    """Apply the parts of `spec` a PromQL selector cannot: projection, ORDER BY, LIMIT.

    Pure. You fetch the rows however you like and hand them here.
    """
    for column, descending in reversed(spec.order_by or []):
        rows.sort(key=lambda row: (row.get(column) is None, row.get(column)), reverse=descending)

    if spec.offset:
        rows = rows[spec.offset :]

    if spec.limit is not None:
        rows = rows[: spec.limit]

    truncated = len(rows) > max_rows
    if truncated:
        rows = rows[:max_rows]

    columns = spec.columns or infer_columns(rows)
    if spec.columns:
        rows = [{column: row.get(column) for column in columns} for row in rows]

    return Result(columns=columns, rows=rows, spec=spec, truncated=truncated)


def infer_columns(rows: list[dict]) -> list[str]:
    """Column order from the rows themselves, with `ts` and `value` last."""
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    tail = [name for name in ("ts", "value") if name in seen]
    return [name for name in seen if name not in tail] + tail
