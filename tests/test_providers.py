from datetime import UTC, datetime

import pytest
from clickhouse_connect.driver.exceptions import DatabaseError, OperationalError

from datum.api.internals.providers import (
    ClickHouseProvider,
    MetricProvider,
    ProviderError,
    QueryRefused,
)


class FakeClient:
    """The driver calls the provider makes, and what it was asked."""

    def __init__(self, columns=(), rows=(), error=None):
        self.columns = list(columns)
        self.rows = list(rows)
        self.error = error
        self.queries: list[tuple] = []
        self.commands: list[str] = []
        self.inserts: list[tuple] = []

    def query(self, sql, parameters=None, settings=None):
        if self.error:
            raise self.error
        self.queries.append((sql, parameters, settings))
        return self

    @property
    def column_names(self):
        return self.columns

    @property
    def result_rows(self):
        return self.rows

    def command(self, statement):
        self.commands.append(statement)

    def insert(self, table, data, column_names, database):
        if self.error:
            raise self.error
        self.inserts.append((table, data, column_names, database))


def build(client=None, **options) -> ClickHouseProvider:
    provider = ClickHouseProvider(host="localhost", **options)
    provider._client = client if client is not None else FakeClient()
    return provider


def test_a_provider_missing_a_method_cannot_be_built():
    class Half(MetricProvider):
        def fetch(self, sql):
            return []

    with pytest.raises(TypeError, match="abstract"):
        Half()


def test_building_a_provider_opens_no_connection():
    assert ClickHouseProvider(host="localhost")._client is None


def test_rows_come_back_keyed_by_column():
    client = FakeClient(columns=["ts", "value"], rows=[[1, 2.5]])

    result = build(client).fetch("SELECT ts, value FROM datum.samples")

    assert result.columns == ["ts", "value"]
    assert result.rows == [{"ts": 1, "value": 2.5}]
    assert result.truncated is False


def test_a_read_that_fills_the_cap_is_reported_as_truncated():
    client = FakeClient(columns=["value"], rows=[[1.0], [2.0]])

    assert build(client, max_rows=2).fetch("SELECT value FROM datum.samples").truncated is True


def test_a_read_cannot_mutate_whatever_the_credential_could():
    client = FakeClient()

    build(client).fetch("SELECT 1")

    assert client.queries[0][2]["readonly"] == 1


def test_an_unreachable_store_is_not_a_refusal():
    client = FakeClient(error=OperationalError("connection refused"))

    with pytest.raises(ProviderError, match="unreachable"):
        build(client).fetch("SELECT 1")


def test_a_refused_query_is_the_callers_fault():
    client = FakeClient(error=DatabaseError("syntax error"))

    with pytest.raises(QueryRefused, match="refused"):
        build(client).fetch("SELCT 1")


def test_a_batch_is_written_in_column_order():
    client = FakeClient()
    row = {
        "ts": datetime(2026, 8, 5, tzinfo=UTC),
        "metric": "cpu",
        "resource_id": "acme",
        "labels": {"region": "ap_south_1"},
        "value": 12.5,
    }

    assert build(client).ingest([row]) == 1
    table, data, columns, database = client.inserts[0]
    assert (table, database) == ("samples", "datum")
    assert columns == ["ts", "metric", "resource_id", "labels", "value"]
    assert data == [[row["ts"], "cpu", "acme", {"region": "ap_south_1"}, 12.5]]


def test_an_empty_batch_touches_the_store_not_at_all():
    client = FakeClient()

    assert build(client).ingest([]) == 0
    assert client.inserts == []


def test_the_schema_is_created_as_configured():
    statements = ("CREATE DATABASE IF NOT EXISTS datum", "CREATE TABLE t")
    client = FakeClient()

    build(client, statements=statements).ensure_schema()

    assert client.commands == list(statements)


def test_label_lookups_are_parameterised_not_interpolated():
    client = FakeClient(columns=["label"], rows=[["region"]])

    assert build(client).get_labels("cpu") == ["region"]
    sql, parameters, _ = client.queries[0]
    assert parameters == {"metric": "cpu"}
    assert "cpu" not in sql
