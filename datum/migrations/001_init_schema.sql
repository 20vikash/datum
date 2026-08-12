CREATE DATABASE IF NOT EXISTS datum;

-- Resources Table
CREATE TABLE IF NOT EXISTS datum.resources
(
    resource_id String,
    status      Enum8('Active' = 1, 'Terminated' = 2, 'Pending' = 3),
    updated_at  DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (resource_id);

-- Metrics Table
CREATE TABLE IF NOT EXISTS datum.samples
(
    ts          DateTime64(3, 'UTC') CODEC(Delta, ZSTD),
    metric      LowCardinality(String),
    resource_id String CODEC(ZSTD),
    labels      Map(LowCardinality(String), String),
    value       Float64 CODEC(Gorilla, ZSTD)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (resource_id, metric, ts);