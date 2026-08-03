# datum

Telemetry over VictoriaMetrics. Two pieces:

- `datum_sql` — a standalone SQL to PromQL translator. No network, no dependencies
  beyond `sqlglot`.
- `datum` — the HTTP service that fetches and serves.

## datum_sql

A metric is a table. Its labels are columns, plus `ts` and `value`. One `SELECT`
becomes one PromQL query.

```python
from datum_sql import plan, shape

spec = plan("""
    SELECT source_id, ts, value
    FROM system_cpu_percent
    WHERE region = 'ap-south-1'
      AND ts > now() - INTERVAL 1 HOUR
    ORDER BY value DESC
    LIMIT 20
""")

spec.selector    # 'system_cpu_percent{region="ap-south-1"}'
spec.start, spec.end, spec.step, spec.mode
spec.describe()  # the whole plan as a dict

result = shape(rows_you_fetched, spec)   # projection, ORDER BY, LIMIT
result.columns, result.rows, result.truncated
```

Fetching is yours. `plan()` tells you what to ask the store for; `shape()`
applies the parts of the query a PromQL selector cannot express.

### How the mapping works

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
| `SELECT a, b` / `ORDER BY` / `LIMIT` | applied by `shape()` to the returned rows |

### What it refuses

PromQL returns one value per series per timestamp. It cannot return two metrics
side by side, so anything needing a second table is refused by name rather than
silently mistranslated:

```
JOIN            -> "JOIN is not supported..."
GROUP BY        -> "GROUP BY is not supported..."
avg(), count()  -> "Aggregate functions are not supported..."
WHERE value > 8 -> "Filtering on value is not supported..."
OR              -> "OR is not supported. Use IN (...)"
```

Fetch the rows and aggregate in your application, or use two queries and combine
the results yourself.

### raw vs step

```python
plan(sql, mode="raw")   # default: only stored samples
plan(sql, mode="step")  # resampled onto a fixed grid, values carried forward
```

`raw` means an instant query with a range selector, so `SELECT *` returns what is
actually stored. `step` means `query_range`, which is what charts want but repeats
the last value across empty grid points — 9 stored samples can come back as 114
rows.

### Safety

- Unbounded queries get a **1 hour** default window (`default_window=`)
- `shape()` caps results at **500 000 rows** (`max_rows=`), with `result.truncated`
- Metric names are used verbatim; producers sanitise `.` to `_` before storing

## Running locally

VictoriaMetrics, on macOS:

```bash
brew install victoriametrics
victoria-metrics -httpListenAddr=127.0.0.1:8428 \
  -storageDataPath=/opt/homebrew/var/victoriametrics-data
```

The service:

```bash
uv sync --all-groups
DATUM_URL=http://127.0.0.1:8428 uv run uvicorn "datum:create_app" --factory --reload
```

## Tests

```bash
uv run pytest
uv run ruff check .
```
