"""The one table Datum stores."""

from __future__ import annotations

import re

TABLE = "samples"
DATABASE = "datum"

# Database and table names are interpolated into SQL, and `qualified` is the key
# the tenant filter is attached under. A name needing quotes would not match the
# table ClickHouse resolves, and reads would go unscoped without erroring.
IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def check_identifier(name: str, what: str) -> str:
    if not IDENTIFIER.match(name):
        raise ValueError(f"{what} must match {IDENTIFIER.pattern}, not {name!r}")
    return name


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

POLICY_SCHEMA = """\
CREATE ROW POLICY OR REPLACE {policy} ON {database}.{table}
USING {label} = getSetting('{setting}')
TO {username}"""


POLICY = "tenant"
RESOURCE_SETTING = "SQL_datum_resource_id"


def get_schema(database: str = DATABASE, table: str = TABLE, username: str = "default"):
    """The table and the policy that scopes it, created together: a deployment
    with the table but not the policy reads across tenants through `merge()`."""
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
