# datum-sql

Query a Prometheus-compatible metrics store (VictoriaMetrics, Prometheus, Thanos)
with SQL. One `SELECT` becomes one PromQL query.

```python
from datum_sql import connect

db = connect("http://localhost:8428", token="...")

db.tables()                                  # metric names
db.columns("system_cpu_percent")             # label names + ts + value
db.distinct("system_cpu_percent", "region")  # values for one label

db.sql("""
    SELECT source_id, ts, value
    FROM system_cpu_percent
    WHERE region = 'ap-south-1'
      AND ts > now() - INTERVAL 1 HOUR
    ORDER BY value DESC
    LIMIT 20
""")
```

## How the mapping works

A metric is a table. Its labels are columns, plus `ts` and `value`.

| SQL | PromQL |
|---|---|
| `FROM system_cpu_percent` | the metric name |
| `WHERE ts > now() - INTERVAL 1 HOUR` | the query window |
| `WHERE region = 'ap'` | `{region="ap"}` |
| `WHERE region != 'ap'` | `{region!="ap"}` |
| `WHERE source_id LIKE 'srv-%'` | `{source_id=~"srv-.*"}` |
| `WHERE region IN ('ap','us')` | `{region=~"ap\|us"}` |
| `WHERE region REGEXP '^ap'` | `{region=~"^ap"}` |
| `WHERE labels['region'] = 'ap'` | `{region="ap"}` (Presto-style access) |
| `SELECT a, b` / `ORDER BY` / `LIMIT` | applied to the returned rows |

Check what a query will do without running it:

```python
db.explain("SELECT * FROM system_cpu_percent WHERE region = 'ap'")
# {'promql': 'system_cpu_percent{region="ap"}', 'start': ..., 'mode': 'raw', ...}
```

## What it refuses

PromQL returns one value per series per timestamp. It cannot return two
metrics side by side, so anything needing a second table is refused by name
rather than silently mistranslated:

```
JOIN            -> "JOIN is not supported..."
GROUP BY        -> "GROUP BY is not supported..."
avg(), count()  -> "Aggregate functions are not supported..."
WHERE value > 8 -> "Filtering on value is not supported..."
OR              -> "OR is not supported. Use IN (...)"
```

Fetch the rows and aggregate in your application, or use two queries and
combine the results yourself.

## raw vs step

```python
connect(url, mode="raw")   # default: only stored samples
connect(url, mode="step")  # resampled onto a fixed grid, values carried forward
```

`raw` uses an instant query with a range selector, so `SELECT *` returns what
is actually stored. `step` uses `query_range`, which is what charts want but
repeats the last value across empty grid points — 9 stored samples can come
back as 114 rows.

## Safety

- Unbounded queries get a **1 hour** default window (`default_window=`)
- Results are capped at **500 000 rows** (`max_rows=`), with `result.truncated`
- Metric names are used verbatim; producers sanitise `.` to `_` before storing

## Install

```bash
pip install -e .        # needs sqlglot
pip install -e '.[arrow]'   # adds result.to_arrow()
```

## Tests

```bash
pytest tests/test_planner.py          # translation, no network
python tests/live_check.py http://localhost:8428   # against a real server
```
