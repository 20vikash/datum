from __future__ import annotations

TABLE = "samples"
LOG_TABLE = "logs"
DATABASE = "datum"

RESOURCE_LABEL = "resource_id"

COLUMNS = (
    "ts",
    "metric",
    RESOURCE_LABEL,
    "labels",
    "value",
)

LOG_COLUMNS = (
    "ts",
    RESOURCE_LABEL,
    "product",
    "service",
    "level",
    "source",
    "message",
    "attributes",
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS {database}.{table}
(
    ts          DateTime64(3, 'UTC') CODEC(Delta, ZSTD),
    metric      LowCardinality(String),
    resource_id LowCardinality(String),
    labels      Map(LowCardinality(String), String),
    value       Float64 CODEC(Gorilla, ZSTD)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (resource_id, metric, ts)
"""


LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS {database}.{table}
(
    ts          DateTime64(3, 'UTC') CODEC(Delta, ZSTD),
    resource_id LowCardinality(String),
    product     LowCardinality(String),
    service     LowCardinality(String),
    level       LowCardinality(String),
    source      LowCardinality(String),
    message     String CODEC(ZSTD),
    attributes  Map(LowCardinality(String), String)
)
ENGINE = MergeTree
PARTITION BY (toYear(ts), toQuarter(ts))
ORDER BY (resource_id, product, service, ts)
"""


def get_schema(database: str = DATABASE, table: str = TABLE):
    """The database and samples table. Datum writes; reads happen directly in ClickHouse."""
    return (
        f"CREATE DATABASE IF NOT EXISTS {database}",
        SCHEMA.format(database=database, table=table),
    )


def get_log_schema(
    database: str = DATABASE,
    table: str = LOG_TABLE,
):
    """The logs table. Datum writes; reads happen directly in ClickHouse."""
    return (
        f"CREATE DATABASE IF NOT EXISTS {database}",
        LOG_SCHEMA.format(database=database, table=table),
    )