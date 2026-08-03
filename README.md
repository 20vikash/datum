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

## The service

Everything documented lives under `/v1`. `/health` is deliberately unversioned
and hidden from the schema, so a future `/v2` never breaks a liveness probe.

| Method | Path | Status |
|---|---|---|
| `POST` | `/v1/ingest` | 501 — needs a written provider |
| `POST` | `/v1/query` | 501 — needs a written provider |
| `POST` | `/v1/query/explain` | works; pure translation, no fetch |
| `GET` | `/v1/metrics` | 501 — needs a written provider |
| `GET` | `/v1/metrics/{metric}/columns` | 501 — needs a written provider |
| `GET` | `/health` | works |

Schema at `/v1/openapi.json`, browsable at `/docs`.

Every `/v1` call needs `Authorization: Bearer <token>`. Central mints tokens;
Datum stores only `sha256(token)` and the identity it maps to. That identity —
tenant, source, and the producer's fixed labels — is stamped onto every sample.
A body claiming a label its own token already fixes is a 400, because otherwise
any host could claim to be another.

## Storage providers

VictoriaMetrics is the only engine that ships, but it reaches the service
through one narrow interface, so swapping it is a new file rather than a
rewrite. Pick one with `DATUM_BACKEND`.

```python
from datum.api.internals.providers import MetricProvider, register


class ClickHouseProvider(MetricProvider):
    name = "clickhouse"

    def __init__(self, url, token=None, **options): ...

    def write(self, samples) -> int: ...
    def fetch(self, spec) -> list[dict]: ...

    @property
    def metrics(self) -> list[str]: ...

    def get_labels(self, metric) -> list[str]: ...
    def get_label_values(self, metric, label) -> list[str]: ...


register(ClickHouseProvider.name, ClickHouseProvider)
```

That is the whole contract. Two rules keep it honest:

- **A provider stores and retrieves; it never queries.** `fetch` receives a
  `QuerySpec` that `datum_sql` already produced, and returns rows. Translation
  and shaping stay in `datum_sql` — a provider that starts interpreting SQL is a
  second query engine.
- **Nothing outside `providers/` knows which one is running.** No branching on
  the backend anywhere else. If a change needs to know, the seam is wrong.

`MetricProvider` is an ABC, so a provider missing a method fails when it is
built rather than returning `None` at request time.

## Running locally

VictoriaMetrics, on macOS:

```bash
brew install victoriametrics
victoria-metrics -httpListenAddr=127.0.0.1:8428 \
  -storageDataPath=/opt/homebrew/var/victoriametrics-data
```

`127.0.0.1` is load-bearing, not a default. VictoriaMetrics has no auth of its
own, so binding it to loopback is what makes FastAPI the only way in — Datum
sends no credential because there is nobody to send one to. Bound to `0.0.0.0`
it would accept reads and writes from anyone who can reach the port, with none
of the token checks above.

The service:

```bash
uv sync --all-groups
cp .env.example .env        # then edit the tokens
uv run uvicorn "datum:create_app" --factory --reload --env-file .env
```

| Variable | Default | Meaning |
|---|---|---|
| `DATUM_URL` | required | where the store lives |
| `DATUM_BACKEND` | `victoriametrics` | which provider to build |
| `DATUM_TOKENS` | none | JSON of accepted token to identity; unset means every `/v1` call is a 401 |
| `DATUM_DIALECT` | `mysql` | SQL dialect the translator parses |
| `DATUM_MODE` | `raw` | `raw` or `step` |

Tokens come from `DATUM_TOKENS`, hand-written for now:

```
DATUM_TOKENS='{"a-secret":{"tenant":"acme","source":"pilot_1","labels":{"region":"ap_south_1"}}}'
```

Single quotes matter — without them `source .env` strips the JSON's own quotes.
Malformed JSON is a startup failure, never a silently empty store.

Opaque hashed tokens are a POC. Production tokens are expected to be JWTs
verified against Central's JWKS, which swaps `TokenStore` for a verifier with
the same `resolve(token) -> Identity | None` shape. The trade to decide then is
revocation: a hashed token dies the moment it is deleted, a signed one stays
valid until it expires.

## Tests

```bash
uv run pytest
uv run ruff check .
```
