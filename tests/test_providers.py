from datetime import UTC, datetime

import pytest
from clickhouse_connect.driver.exceptions import DatabaseError, OperationalError

from datum.api.internals.providers import (
    ClickHouseProvider,
    MetricProvider,
    ProviderError,
    QueryRefused,
)
from datum.config.clickhouse import get_schema


class FakeClient:
    """The driver calls the provider makes, and what it was asked."""

    def __init__(self, error=None):
        self.error = error
        self.commands: list[str] = []
        self.inserts: list[tuple] = []

    def command(self, statement):
        if self.error:
            raise self.error
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
        def ingest(self, rows):
            return 0

    with pytest.raises(TypeError, match="abstract"):
        Half()


def test_building_a_provider_opens_no_connection():
    assert ClickHouseProvider(host="localhost")._client is None


def test_a_provider_exposes_no_way_to_read():
    """Reads are Insights' job, direct. A read method here would be a second door."""
    for absent in ("fetch", "get_metrics", "get_labels", "get_label_values", "get_columns"):
        assert not hasattr(MetricProvider, absent)


def test_an_unreachable_store_is_not_a_refusal():
    client = FakeClient(error=OperationalError("connection refused"))

    with pytest.raises(ProviderError, match="unreachable"):
        build(client).ingest([{column: None for column in ROW}])


def test_a_refused_write_is_the_callers_fault():
    client = FakeClient(error=DatabaseError("unknown column"))

    with pytest.raises(QueryRefused, match="refused"):
        build(client).ingest([{column: None for column in ROW}])


ROW = {
    "ts": datetime(2026, 8, 5, tzinfo=UTC),
    "metric": "cpu",
    "resource_id": "acme",
    "labels": {"region": "ap_south_1"},
    "value": 12.5,
}


def test_a_batch_is_written_in_column_order():
    client = FakeClient()

    assert build(client).ingest([ROW]) == 1
    table, data, columns, database = client.inserts[0]
    assert (table, database) == ("samples", "datum")
    assert columns == ["ts", "metric", "resource_id", "labels", "value"]
    assert data == [[ROW["ts"], "cpu", "acme", {"region": "ap_south_1"}, 12.5]]


def test_an_empty_batch_touches_the_store_not_at_all():
    client = FakeClient()

    assert build(client).ingest([]) == 0
    assert client.inserts == []


def test_the_schema_is_created_where_it_is_configured():
    client = FakeClient()

    build(client, database="other", table="readings").ensure_schema()

    assert client.commands == list(get_schema("other", "readings"))


def test_the_schema_creates_the_database_and_one_table():
    client = FakeClient()

    build(client).ensure_schema()

    assert len(client.commands) == 2
    assert client.commands[0].startswith("CREATE DATABASE IF NOT EXISTS datum")
    assert "CREATE TABLE IF NOT EXISTS datum.samples" in client.commands[1]


def test_startup_asks_clickhouse_for_nothing_but_the_schema():
    """No SHOW GRANTS and no row policy: what a credential may reach is granted
    at provisioning time, not audited here."""
    client = FakeClient()

    build(client).ensure_schema()

    assert not any("GRANT" in command or "POLICY" in command for command in client.commands)
