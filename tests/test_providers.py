from datetime import UTC, datetime

import clickhouse_connect
import pytest
from clickhouse_connect.driver.exceptions import DatabaseError, OperationalError

from datum.api.internals.providers import (
    ClickHouseProvider,
    MetricProvider,
    ProviderError,
    QueryRefused,
)
from datum.config.clickhouse import RESOURCE_SETTING, get_schema


class FakeClient:
    """The driver calls the provider makes, and what it was asked."""

    def __init__(self, columns=(), rows=(), error=None):
        self.columns = list(columns)
        self.rows = list(rows)
        self.error = error
        self.server_settings: dict = {}
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


RESOURCE = "acme"


def test_a_provider_missing_a_method_cannot_be_built():
    class Half(MetricProvider):
        def fetch(self, sql, resource_id):
            return []

    with pytest.raises(TypeError, match="abstract"):
        Half()


def test_building_a_provider_opens_no_connection():
    assert ClickHouseProvider(host="localhost")._client is None


def test_rows_come_back_keyed_by_column():
    client = FakeClient(columns=["ts", "value"], rows=[[1, 2.5]])

    result = build(client).fetch("SELECT ts, value FROM datum.samples", RESOURCE)

    assert result.columns == ["ts", "value"]
    assert result.rows == [{"ts": 1, "value": 2.5}]
    assert result.truncated is False


def test_a_read_that_fills_the_cap_is_reported_as_truncated():
    client = FakeClient(columns=["value"], rows=[[1.0], [2.0]])
    provider = build(client, max_rows=2)

    assert provider.fetch("SELECT value FROM datum.samples", RESOURCE).truncated is True


def test_a_read_cannot_mutate_whatever_the_credential_could():
    client = FakeClient()

    build(client).fetch("SELECT 1", RESOURCE)

    assert client.queries[0][2]["readonly"] == 1


def test_a_read_is_scoped_to_its_resource_id_whatever_the_sql_says():
    """The filter is on the table, so `SELECT * FROM samples` still cannot
    read another tenant."""
    client = FakeClient()

    build(client).fetch("SELECT * FROM datum.samples", RESOURCE)

    filters = client.queries[0][2]["additional_table_filters"]
    assert filters == {"datum.samples": "resource_id = 'acme'"}


def test_a_resource_id_cannot_break_out_of_its_literal():
    client = FakeClient()

    build(client).fetch("SELECT 1", "acme' OR 1=1 --")

    filters = client.queries[0][2]["additional_table_filters"]
    assert filters == {"datum.samples": "resource_id = 'acme\\' OR 1=1 --'"}


def test_every_read_is_scoped_not_only_the_query_route():
    client = FakeClient(columns=["metric"], rows=[["cpu"]])
    provider = build(client)

    provider.get_metrics(RESOURCE)
    provider.get_labels("cpu", RESOURCE)
    provider.get_label_values("cpu", "region", RESOURCE)

    assert all(
        "resource_id = 'acme'" in query[2]["additional_table_filters"].values()
        for query in client.queries
    )


def test_an_unreachable_store_is_not_a_refusal():
    client = FakeClient(error=OperationalError("connection refused"))

    with pytest.raises(ProviderError, match="unreachable"):
        build(client).fetch("SELECT 1", RESOURCE)


def test_a_refused_query_is_the_callers_fault():
    client = FakeClient(error=DatabaseError("syntax error"))

    with pytest.raises(QueryRefused, match="refused"):
        build(client).fetch("SELCT 1", RESOURCE)


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


def test_the_schema_is_created_where_it_is_configured():
    client = FakeClient()

    build(client, database="other", table="readings", username="reader").ensure_schema()

    assert client.commands == list(get_schema("other", "readings", "reader"))


def test_the_policy_is_created_with_the_table_not_after_it():
    """A deployment with the table but no policy reads across tenants through
    `merge()`, so the two are not separable."""
    client = FakeClient()

    build(client).ensure_schema()

    policy = [command for command in client.commands if "ROW POLICY" in command]
    assert len(policy) == 1
    assert "ON datum.samples" in policy[0]
    assert f"getSetting('{RESOURCE_SETTING}')" in policy[0]


def test_a_read_carries_both_filters():
    """The policy binds to the table and holds however the rows are reached; the
    table filter covers the direct read if a server's policy is missing."""
    client = FakeClient()

    build(client).fetch("SELECT 1", RESOURCE)

    settings = client.queries[0][2]
    assert settings[RESOURCE_SETTING] == RESOURCE
    assert settings["additional_table_filters"] == {"datum.samples": "resource_id = 'acme'"}


# What ClickHouse 26.8 actually prints for SHOW GRANTS, not a paraphrase of it.
SCOPED_GRANTS = [
    "GRANT CREATE DATABASE, CREATE TABLE, CREATE ROW POLICY ON datum.* TO datum",
    "GRANT SELECT, INSERT ON datum.samples TO datum",
]


def test_the_documented_grants_are_enough_to_start():
    client = FakeClient(columns=["grant"], rows=[[line] for line in SCOPED_GRANTS])

    build(client).check_privileges()


@pytest.mark.parametrize(
    "grant",
    [
        "GRANT SELECT ON *.* TO datum",
        "GRANT SELECT ON system.* TO datum",
        "GRANT SELECT ON other.* TO datum",
    ],
)
def test_a_credential_that_reaches_past_its_table_stops_startup(grant):
    """The row policy covers one table. A grant past it is a read that leaves
    its resource_id through a table no policy sees."""
    rows = [[line] for line in (*SCOPED_GRANTS, grant)]
    client = FakeClient(columns=["grant"], rows=rows)

    with pytest.raises(ProviderError, match="holds grants past datum.samples") as refused:
        build(client).check_privileges()

    assert grant in str(refused.value)


def test_the_driver_is_told_about_the_custom_setting(monkeypatch):
    """It is absent from system.settings, so an untaught driver drops it and
    every read fails closed."""
    client = FakeClient()
    monkeypatch.setattr(clickhouse_connect, "get_client", lambda **_: client)

    provider = ClickHouseProvider(host="localhost")

    assert provider.client.server_settings[RESOURCE_SETTING].name == RESOURCE_SETTING


def test_label_lookups_are_parameterised_not_interpolated():
    client = FakeClient(columns=["label"], rows=[["region"]])

    assert build(client).get_labels("cpu", RESOURCE) == ["region"]
    sql, parameters, _ = client.queries[0]
    assert parameters == {"metric": "cpu"}
    assert "cpu" not in sql
