-- Target table for ingestion stats (for rogue metric detection)
CREATE TABLE IF NOT EXISTS datum.daily_ingestion_stats
(
    date        Date,
    resource_id String,
    metric_count SimpleAggregateFunction(sum, UInt64)
)
ENGINE = SummingMergeTree()
ORDER BY (date, resource_id);

-- Materialized View
CREATE MATERIALIZED VIEW IF NOT EXISTS datum.mv_daily_ingestion_stats 
TO datum.daily_ingestion_stats AS
SELECT
    toDate(ts) AS date,
    resource_id,
    count() AS metric_count
FROM datum.samples
GROUP BY date, resource_id;