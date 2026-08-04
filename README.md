# datum

Datum stores numbers about your fleet. Producers push them in. You read them
back with SQL.

Three parts:

| Part | What it is | Who uses it |
|---|---|---|
| `datum` | the HTTP service | runs on a server |
| `datum_client` | the thing producers import to push | Pilot, agents |
| `datum_sql` | turns SQL into PromQL | the service, and Insights |

VictoriaMetrics does the storing. Nothing sits between the service and it — no
queue, no worker.

```
producers --POST /v1/ingest--> datum --> VictoriaMetrics
                                 ^
                    readers --POST /v1/query
```

---

# The service

## Endpoints

Everything real lives under `/v1`. `/health` does not, so a future `/v2` cannot
break a health check.

| Method | Path | Works? |
|---|---|---|
| `POST` | `/v1/ingest` | **yes** |
| `POST` | `/v1/query/explain` | **yes** — pure translation, never touches the store |
| `POST` | `/v1/query` | no — 501, reading is not written yet |
| `GET` | `/v1/metrics` | no — 501 |
| `GET` | `/v1/metrics/{metric}/columns` | no — 501 |
| `GET` | `/health` | **yes** |

Browse them at `/docs`. Raw schema at `/v1/openapi.json`.

## Sending data

```bash
curl -X POST http://localhost:8000/v1/ingest \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"samples":[
        {"metric":"system_cpu_percent","value":12.5,
         "ts":"2026-08-04T09:00:00Z","labels":{"host":"a"}}
      ]}'
```

Reply: `{"accepted": 1}` with status 202.

Rules for a sample:

- `metric` — lowercase, underscores. No dots. Required.
- `value` — a real number. `NaN` and `Inf` are rejected. Required.
- `ts` — RFC 3339. **Required.** Datum will not guess it for you.
- `labels` — optional. Up to 30.

Anything else in the body is rejected. Better to fail loudly than store junk.

## Tokens

Every `/v1` call needs `Authorization: Bearer <token>`.

Datum keeps only `sha256(token)`. Each token maps to an identity: a tenant, a
source, and some fixed labels.

Datum adds that identity to every sample you send:

```
you send:    system_cpu_percent{host="a"}
gets stored: system_cpu_percent{host="a", tenant_id="acme",
                                source_id="pilot_1", region="ap_south_1"}
```

So do **not** send `tenant_id`, `source_id`, or any label your token already
sets. Those come back as 400. That is what stops one host pretending to be
another.

## What each status means

| Status | Meaning |
|---|---|
| 202 | stored |
| 400 | you sent a label the token already sets |
| 401 | token missing, wrong, or revoked |
| 422 | a sample broke a rule; the reply says which field and which sample |
| 501 | that part is not written yet |
| 503 | Datum is up, VictoriaMetrics is not |

## Running it locally

Start VictoriaMetrics:

```bash
brew install victoriametrics
victoria-metrics -httpListenAddr=127.0.0.1:8428 \
  -storageDataPath=/opt/homebrew/var/victoriametrics-data
```

**`127.0.0.1` matters.** VictoriaMetrics has no login of its own. Loopback is
what makes Datum the only way in. Bind it to `0.0.0.0` and anyone who reaches
the port can read and write everything, with no token needed.

Make a `.env` file. It is not in the repo — it holds secrets:

```
DATUM_URL=http://127.0.0.1:8428
DATUM_BACKEND=victoriametrics
DATUM_TOKENS='{"a-secret":{"tenant":"acme","source":"pilot_1","labels":{"region":"ap_south_1"}}}'
```

Single quotes around the JSON matter. Without them `source .env` eats the
quotes inside. Bad JSON stops the service at startup — it never runs with an
empty token list by accident.

Make a token with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then run it:

```bash
uv sync --all-groups
uv run uvicorn "datum:create_app" --factory --reload --env-file .env
```

| Variable | Default | What it does |
|---|---|---|
| `DATUM_URL` | required | where VictoriaMetrics is |
| `DATUM_BACKEND` | `victoriametrics` | which storage provider to use |
| `DATUM_TOKENS` | none | who may push. Unset means every call is a 401 |
| `DATUM_DIALECT` | `mysql` | SQL flavour the translator reads |
| `DATUM_MODE` | `raw` | `raw` or `step` |

## Putting it on a server

Linux only. Runs as your own user — no root, no sudo.

```bash
git clone https://github.com/frappe/Datum.git ~/datum
cd ~/datum && uv sync --all-groups

mkdir -p ~/services
# write ~/services/datum.env with the vars above
chmod 600 ~/services/datum.env

.venv/bin/python bootstrap.py
```

You get two services:

```
~/services/                     the unit files and datum.env live here
~/.config/systemd/user/         symlinks, because that is where systemd looks
~/.local/share/datum/           the metrics data
```

```bash
systemctl --user status datum-api
journalctl --user -u datum-api -f
```

Run it twice and nothing happens — it only restarts a service whose unit
actually changed.

Two things it does not do: install VictoriaMetrics (it checks your PATH and
tells you where to get it), and write `datum.env` (that is yours, it holds
tokens).

**No HTTPS.** Tokens travel in plain text. Fine on loopback or a private
network. Put a TLS proxy in front before real hosts push to it.

## Swapping the storage engine

VictoriaMetrics is the only one that ships. But it plugs in through one small
interface, so adding another is a new file, not a rewrite.

```python
from datum.api.internals.providers import PROVIDERS, MetricProvider


class ClickHouseProvider(MetricProvider):
    name = "clickhouse"

    def __init__(self, url, **options): ...

    def write(self, samples) -> int: ...
    def fetch(self, spec) -> list[dict]: ...

    @property
    def metrics(self) -> list[str]: ...

    def get_labels(self, metric) -> list[str]: ...
    def get_label_values(self, metric, label) -> list[str]: ...


PROVIDERS["clickhouse"] = ClickHouseProvider
```

Pick it with `DATUM_BACKEND=clickhouse`.

Two rules:

- **A provider stores and fetches. It never reads SQL.** `fetch` gets a plan
  that `datum_sql` already made. A provider that starts parsing SQL is a second
  query engine, which is the thing this seam exists to stop.
- **Nothing outside `providers/` knows which one is running.** If some other
  code needs to know, the seam is wrong — fix that, not the code.

`MetricProvider` is an ABC. Miss a method and it fails when built, not halfway
through a request.

---

# The client

Producers should not hand-write HTTP or metric names. Use `datum_client`. It
needs no installs beyond the standard library.

```python
from datum_client import Batch, Datum

datum = Datum("https://datum.internal", token=DATUM_TOKEN)

memory = Batch("system", "memory")
memory.gauge("used", 1154545090, "bytes")     # system_memory_used_bytes

datum.send(memory)
```

It builds names for you, keeps them consistent, and blocks labels that would
wreck the store — like `pid`, which makes a brand new series on every restart.

Full guide: [`datum_client/README.md`](datum_client/README.md).

---

# datum_sql

Turns SQL into PromQL. Standalone — no network, and it never imports the
service. Works against VictoriaMetrics, Prometheus or Thanos.

A metric is a table. Its labels are the columns, plus `ts` and `value`. One
`SELECT` becomes one PromQL query.

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
spec.describe()  # the whole plan as a dict

result = shape(rows_you_fetched, spec)
result.columns, result.rows, result.truncated
```

Fetching is yours. `plan()` says what to ask for. `shape()` does the parts
PromQL cannot.

## How the mapping works

| SQL | PromQL |
|---|---|
| `FROM system_cpu_percent` | the metric name |
| `WHERE ts > now() - INTERVAL 1 HOUR` | the query window |
| `WHERE region = 'ap'` | `{region="ap"}` |
| `WHERE region != 'ap'` | `{region!="ap"}` |
| `WHERE source_id LIKE 'srv-%'` | `{source_id=~"srv-.*"}` |
| `WHERE region IN ('ap','us')` | `{region=~"ap\|us"}` |
| `WHERE region REGEXP '^ap'` | `{region=~"^ap"}` |
| `WHERE labels['region'] = 'ap'` | `{region="ap"}` (Presto style) |
| `SELECT a, b` / `ORDER BY` / `LIMIT` / `OFFSET` | done by `shape()` on the rows you fetched |

`ORDER BY` and `LIMIT` rank **rows**, not series. `ORDER BY value DESC LIMIT 5`
gives the five highest samples, which may all belong to one series. That is not
`topk(5, ...)`, which gives five series. `shape()` sorts every fetched row before
applying the limit, so the rows you get are the right ones — but the whole window
is fetched first, because a selector cannot rank on value.

## What it refuses

One SELECT becomes one selector. PromQL itself can combine metrics — binary
operators match series on their labels — but that is a second query engine's job,
so anything needing it is refused by name rather than guessed at:

```
JOIN            -> "JOIN is not supported..."
UNION           -> "UNION is not supported..."
GROUP BY        -> "GROUP BY is not supported..."
avg(), count()  -> "Aggregate functions are not supported..."
WHERE value > 8 -> "Filtering on value is not supported..."
OR              -> "OR is not supported. Use IN (...)"
subquery        -> "subquery is not supported..."
```

`LIMIT` and `OFFSET` are honoured, but they are not pushed down — PromQL has no
`LIMIT`, so the whole window is fetched and `shape()` slices it. They bound what
you receive, never what is read.

Fetch the rows and do it in your own code, or run two queries.

Why `WHERE value > 8` cannot work: labels are an index, values are not. Datum
would have to fetch everything and filter in Python, which looks like it works
until the day it does not.

## raw vs step

```python
plan(sql, mode="raw")    # default: only what is stored
plan(sql, mode="step")   # on a fixed grid, repeating the last value
```

`raw` gives you the real samples. `step` is what charts want, but it repeats
values across gaps — 9 stored samples can come back as 114 rows.

## Safety

- No time range in the query? You get **1 hour**, never all of retention.
- `shape()` stops at **500 000 rows** and sets `result.truncated`.
- Metric names are used as-is. Producers turn `.` into `_` before sending.

---

# Tests

```bash
uv run pytest
uv run ruff check .
```
