from __future__ import annotations

from datetime import UTC, datetime

import pytest
from clickhouse_connect.driver.exceptions import DatabaseError, OperationalError

from datum.api.internals.providers import (
    ClickHouseLogProvider,
    LogProvider,
    ProviderError,
    QueryRefused,
)
from datum.config.clickhouse import get_log_schema


class FakeClient:
    """The driver calls the log provider makes, and what it was asked."""

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


def build(client=None, **options) -> ClickHouseLogProvider:
    provider = ClickHouseLogProvider(host="localhost", **options)
    provider._client = client if client is not None else FakeClient()
    return provider


ROW = {
    "ts": datetime(2026, 8, 5, tzinfo=UTC),
    "resource_id": "acme",
    "product": "pilot",
    "service": "worker",
    "level": "info",
    "source": "worker_pool.log",
    "message": "job done",
    "attributes": {"queue": "default"},
}


def test_a_log_provider_missing_a_method_cannot_be_built():
    class Half(LogProvider):
        def ensure_schema(self):
            pass

    with pytest.raises(TypeError, match="abstract"):
        Half()


def test_building_a_log_provider_opens_no_connection():
    assert ClickHouseLogProvider(host="localhost")._client is None


def test_a_log_provider_exposes_no_way_to_read():
    """Reads are Insights' job, direct. A read method here would be a second door."""
    for absent in ("fetch", "get_products", "get_services"):
        assert not hasattr(LogProvider, absent)


def test_an_unreachable_log_store_is_not_a_refusal():
    client = FakeClient(error=OperationalError("connection refused"))

    with pytest.raises(ProviderError, match="unreachable"):
        build(client).ingest([ROW])


def test_a_refused_log_write_is_the_callers_fault():
    client = FakeClient(error=DatabaseError("unknown column"))

    with pytest.raises(QueryRefused, match="refused"):
        build(client).ingest([ROW])


def test_a_log_batch_is_written_in_column_order():
    client = FakeClient()

    assert build(client).ingest([ROW]) == 1
    table, data, columns, database = client.inserts[0]
    assert (table, database) == ("logs", "datum")
    assert columns == [
        "ts",
        "resource_id",
        "product",
        "service",
        "level",
        "source",
        "message",
        "attributes",
    ]
    assert data == [
        [
            ROW["ts"],
            "acme",
            "pilot",
            "worker",
            "info",
            "worker_pool.log",
            "job done",
            {"queue": "default"},
        ]
    ]


def test_an_empty_log_batch_touches_the_store_not_at_all():
    client = FakeClient()

    assert build(client).ingest([]) == 0
    assert client.inserts == []


def test_the_log_schema_is_created_where_it_is_configured():
    client = FakeClient()

    build(client, database="other", table="log_lines").ensure_schema()

    assert client.commands == list(get_log_schema("other", "log_lines"))


def test_the_log_schema_creates_the_database_and_one_table():
    client = FakeClient()

    build(client).ensure_schema()

    assert len(client.commands) == 2
    assert client.commands[0].startswith("CREATE DATABASE IF NOT EXISTS datum")
    assert "CREATE TABLE IF NOT EXISTS datum.logs" in client.commands[1]


def test_log_schema_creation_asks_clickhouse_for_nothing_but_the_schema():
    """No row policy and no SHOW GRANTS: who may read is granted at provisioning
    time, not policed or audited here."""
    client = FakeClient()

    build(client).ensure_schema()

    assert not any("POLICY" in command or "GRANT" in command for command in client.commands)
