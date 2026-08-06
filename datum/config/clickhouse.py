from __future__ import annotations

TABLE = "samples"
DATABASE = "datum"

RESOURCE_LABEL = "resource_id"
COLUMNS = ("ts", "metric", RESOURCE_LABEL, "labels", "value")

POLICY = "tenant"
RESOURCE_SETTING = "SQL_datum_resource_id"


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

POLICY_SCHEMA = """\
CREATE ROW POLICY OR REPLACE {policy} ON {database}.{table}
USING {label} = getSetting('{setting}')
TO {username}"""


def get_schema(database: str = DATABASE, table: str = TABLE, username: str = "default"):
    """Table and policy together: one without the other leaks through `merge()`."""
    return (
        f"CREATE DATABASE IF NOT EXISTS {database}",
        SCHEMA.format(database=database, table=table),
        POLICY_SCHEMA.format(
            policy=POLICY,
            database=database,
            table=table,
            label=RESOURCE_LABEL,
            setting=RESOURCE_SETTING,
            username=username,
        ),
    )
