"""The one table Datum stores."""

from __future__ import annotations

TABLE = "samples"
DATABASE = "datum"

RESOURCE_LABEL = "resource_id"
COLUMNS = ("ts", "metric", RESOURCE_LABEL, "labels", "value")

# resource_id is lifted out of labels because it is the tenant boundary, so it
# has to be a sort key rather than a map lookup. No TTL: nothing here expires.
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
    return (
        f"CREATE DATABASE IF NOT EXISTS {database}",
        SCHEMA.format(database=database, table=table),
    )
