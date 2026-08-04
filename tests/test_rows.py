from datetime import UTC, datetime

from datum_sql import QuerySpec, infer_columns, shape

START = datetime(2026, 8, 3, tzinfo=UTC)
END = datetime(2026, 8, 3, 1, tzinfo=UTC)

ROWS = [
    {"host": "a", "ts": 3, "value": 1.0},
    {"host": "b", "ts": 1, "value": 3.0},
    {"host": "c", "ts": 2, "value": 2.0},
]


def make_spec(**overrides) -> QuerySpec:
    return QuerySpec(metric="cpu", start=START, end=END, step="15s", **overrides)


def test_columns_are_inferred_with_ts_and_value_last():
    assert infer_columns(ROWS) == ["host", "ts", "value"]


def test_order_by_ascending():
    result = shape(list(ROWS), make_spec(order_by=[("ts", False)]))

    assert [row["ts"] for row in result.rows] == [1, 2, 3]


def test_order_by_descending():
    result = shape(list(ROWS), make_spec(order_by=[("value", True)]))

    assert [row["value"] for row in result.rows] == [3.0, 2.0, 1.0]


def test_missing_values_sort_last():
    rows = [{"host": "a"}, {"host": "b", "ts": 1}]

    result = shape(rows, make_spec(order_by=[("ts", False)]))

    assert result.rows[0]["host"] == "b"


def test_limit_applies_after_ordering():
    result = shape(list(ROWS), make_spec(order_by=[("ts", False)], limit=2))

    assert [row["ts"] for row in result.rows] == [1, 2]


def test_projection_narrows_columns():
    result = shape(list(ROWS), make_spec(columns=["host"]))

    assert result.columns == ["host"]
    assert result.rows[0] == {"host": "a"}


def test_truncation_is_reported():
    result = shape(list(ROWS), make_spec(), max_rows=2)

    assert result.truncated is True
    assert len(result) == 2


def test_ordering_sees_every_row_before_truncation():
    """The top row must be the global maximum, not the best of an arbitrary prefix."""
    rows = [{"host": str(index), "ts": index, "value": float(index)} for index in range(10)]

    result = shape(rows, make_spec(order_by=[("value", True)], limit=2), max_rows=3)

    assert [row["value"] for row in result.rows] == [9.0, 8.0]


def test_limit_within_max_rows_is_not_truncated():
    """A satisfied LIMIT is the whole answer, however many rows were fetched."""
    rows = [{"host": str(index), "ts": index, "value": float(index)} for index in range(10)]

    result = shape(rows, make_spec(order_by=[("value", True)], limit=2), max_rows=3)

    assert result.truncated is False


def test_untruncated_result_says_so():
    result = shape(list(ROWS), make_spec())

    assert result.truncated is False
    assert result.tuples()[0] == ("a", 3, 1.0)


def test_offset_skips_rows_before_limit():
    result = shape(list(ROWS), make_spec(order_by=[("ts", False)], limit=1, offset=1))

    assert [row["ts"] for row in result.rows] == [2]


def test_offset_past_the_end_gives_nothing():
    result = shape(list(ROWS), make_spec(offset=99))

    assert result.rows == []
