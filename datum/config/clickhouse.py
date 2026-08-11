from __future__ import annotations

TABLE = "samples"
DATABASE = "datum"

RESOURCE_LABEL = "resource_id"
COLUMNS = ("ts", "metric", RESOURCE_LABEL, "labels", "value")


SCHEMA = """\
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
ORDER BY (resource_id, metric, ts)"""


def get_schema(database: str = DATABASE, table: str = TABLE):
    """The database and the one table. Datum writes; who may read is granted, not policed."""
    return (
        f"CREATE DATABASE IF NOT EXISTS {database}",
        SCHEMA.format(database=database, table=table),
    )
