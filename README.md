# datum

Datum stores numbers about your fleet. Producers push them in. You read them
back with SQL.

Three parts:

| Part | What it is | Who uses it |
|---|---|---|
| `datum` | the HTTP service | runs on a server |
| `datum_client` | the thing producers import to push | Pilot, agents |
| `datum_sql` | turns SQL into PromQL | the service, and Insights |

VictoriaMetrics does the storing. Nothing queues or buffers on the way in —
vmauth checks the token and passes the bytes straight through.

```
producers  --POST /api/v1/import--┐
 (JSON)                           ├--> vmauth --> VictoriaMetrics
collectors --POST /api/v1/write---┘      (JWT)         ^
 (remote write)                                        |
                          readers --POST /v1/query--> datum
```

Writes never touch Python. vmauth verifies the JWT and proxies straight to
VictoriaMetrics, which stamps identity from the token's claim. Datum serves
reads only.

---

# The service

## Endpoints

Everything real lives under `/v1`. `/health` does not, so a future `/v2` cannot
break a health check.

| Method | Path | Works? |
|---|---|---|
| `POST` | `/v1/query` | **yes** — SQL in, rows out |
| `POST` | `/v1/query/explain` | **yes** — pure translation, never touches the store |
| `GET` | `/v1/metrics` | **yes** |
| `GET` | `/v1/metrics/{metric}/columns` | **yes** |
| `GET` | `/health` | **yes** |

There is no write endpoint here. Producers go to vmauth.

Browse them at `/docs`. Raw schema at `/v1/openapi.json`.

## Sending data

Producers talk to **vmauth**, not to this service. It listens on `:8427`, checks
the JWT, and hands the body to VictoriaMetrics unchanged.

JSON, which is what `datum_client` sends:

```bash
curl -X POST http://localhost:8427/api/v1/import \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"metric":{"__name__":"system_cpu_percent","host":"a"},
       "values":[12.5],"timestamps":[1785857020273]}'
```

Prometheus remote write, which is what vmagent sends:

```yaml
remote_write:
  - url: http://localhost:8427/api/v1/write
    authorization:
      credentials: YOUR_JWT
```

Both answer `204`. Only those two paths are proxied — a write token that tries
`/api/v1/query` gets a `400`, so it can never read another tenant's series.

**Datum no longer validates samples.** VictoriaMetrics accepts what it is given,
so a metric name with a dot in it is now stored rather than refused. Identity is
still enforced, because the token's labels overwrite whatever the body claimed.

## Tokens

Every call carries a JWT that Central signed: `Authorization: Bearer <jwt>`.

Identity lives in the `vm_access` claim:

```json
{"vm_access": {"metrics_extra_labels": ["tenant_id=acme", "source_id=pilot_1"]}}
```

vmauth turns those into `extra_label` query args and VictoriaMetrics applies
them **over** whatever the body carried:

```
you send:    system_cpu_percent{host="a", tenant_id="someone_else"}
gets stored: system_cpu_percent{host="a", tenant_id="acme", source_id="pilot_1"}
```

A spoofed label loses rather than being refused. That is the one behaviour that
changed with vmauth: it overrides silently instead of answering 400.

Datum verifies the same JWT the same way for reads — the same key file, or the
same issuer — so one token works for both. Signatures are RSA or ECDSA: vmauth
does not accept HMAC, so neither does Datum.

## What each status means

| Status | Where | Meaning |
|---|---|---|
| 204 | vmauth | stored |
| 400 | datum | the SQL asks for something one PromQL query cannot do |
| 400 | vmauth | that path is not proxied; only writes are |
| 401 | both | JWT missing, unsigned, expired, or signed by the wrong key |
| 422 | datum | the request body broke the schema |
| 503 | datum | Datum is up, VictoriaMetrics is not |

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

Save Central's public key somewhere, then run it:

```bash
uv sync --all-groups
DATUM_URL=http://127.0.0.1:8428 \
DATUM_JWT_PUBLIC_KEY_FILE=~/services/central.pub \
  uv run uvicorn "datum:create_app" --factory --reload
```

No key means every call is a 401. A key path that does not exist is a startup
failure, not a service that quietly refuses everyone.

| Variable | Default | What it does |
|---|---|---|
| `DATUM_URL` | required | where VictoriaMetrics is |
| `DATUM_JWT_PUBLIC_KEY_FILE` | none | PEM Central signs with |
| `DATUM_OIDC_ISSUER` | none | fetch the key set from the issuer instead. With neither, every call is a 401 |
| `DATUM_DIALECT` | `mysql` | SQL flavour the translator reads |
| `DATUM_MODE` | `raw` | `raw` or `step` |
| `DATUM_IGNORE_PAGINATION` | `1` | drop `LIMIT`/`OFFSET` sent by BI tools. `0` honours them |

## Putting it on a server

Linux only. Runs as your own user — no root, no sudo.

```bash
git clone https://github.com/frappe/Datum.git ~/datum
cd ~/datum && uv sync --all-groups

# put Central's public key somewhere, then:
.venv/bin/python bootstrap.py --public-key ~/services/central.pub
```

`bootstrap.py` asks if you leave the verification out, and `--dry-run` prints
every file it would write without touching anything. `--help` lists the rest:
`--vmauth-listen`, `--datum-port`, `--retention`, `--config-dir`.

Moving to a JWKS endpoint later is one flag:

```bash
.venv/bin/python bootstrap.py --oidc-issuer https://central.frappe.io
```

You get three services — `victoria-metrics`, `vmauth` and `datum-api`:

```
~/services/                     unit files and vmauth.yml, all generated
~/.config/systemd/user/         symlinks, because that is where systemd looks
~/.local/share/datum/           the metrics data
~/.local/share/datum/logs/      access.log, error.log, vmauth-*.log
```

There is no env file. Each unit carries what it needs, and the public key stays
a file on disk that both vmauth and datum-api read — so the two can never end
up verifying against different keys.

```bash
systemctl --user status datum-api
tail -f ~/.local/share/datum/logs/access.log
```

The unit sends stdout to `access.log` and stderr to `error.log`, which is how
uvicorn splits them. They go to the files instead of the journal, and nothing
rotates them — add a logrotate rule before they matter.

Run it twice and nothing happens — it only restarts a service whose unit
actually changed.

One thing it does not do: install VictoriaMetrics or vmauth. It checks your PATH
and tells you where to get them.

Passing more than one of `--public-key`, `--oidc-issuer` and `--skip-verify` is
a startup failure rather than a silent pick. So is pointing `--public-key` at a
file that is not there — it fails before anything is written.

`--oidc-issuer` configures both sides: vmauth verifies writes against the
fetched key set and datum-api verifies reads against the same one, refreshing
every five minutes to match vmauth. Tokens must carry an `iss` matching the
issuer exactly, which is what vmauth requires too.

While the issuer is unreachable, reads answer 401 rather than being let
through. `--skip-verify` leaves reads closed on purpose: writes are open and
reads are not, which is the shape a local testing mode should have.

**No HTTPS.** Tokens travel in plain text. Fine on loopback or a private
network. Put a TLS proxy in front before real hosts push to it.

## Swapping the storage engine

VictoriaMetrics is the only one that ships. But it plugs in through one small
interface, so adding another is a new file, not a rewrite.

```python
from datum.api.internals.providers import MetricProvider


class ClickHouseProvider(MetricProvider):
    name = "clickhouse"

    def __init__(self, url, **options): ...

    def fetch(self, spec) -> list[dict]: ...

    @property
    def metrics(self) -> list[str]: ...

    def get_labels(self, metric) -> list[str]: ...
    def get_label_values(self, metric, label) -> list[str]: ...

```

`app.py` builds it directly — there is no backend registry, because
VictoriaMetrics is the only one that ships. A second engine is a new file here
and one changed line there.

Two rules:

- **A provider fetches. It never reads SQL, and it never writes.** `fetch` gets a plan
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

`LIMIT` and `OFFSET` are honoured, but never pushed down — PromQL has no `LIMIT`,
so the whole window is fetched and `shape()` slices it. They bound what you
receive, never what is read.

The service drops them instead. Paging a metric query does not work: the window
is relative, so page 2 asks about a slightly later hour and `OFFSET` skips into a
set that has moved, quietly repeating and skipping rows. `DATUM_IGNORE_PAGINATION`
is on by default, which throws away the page window — and the subquery a BI tool
wraps around a query that already had a `LIMIT`. `ORDER BY` is kept. Set it to `0`
to honour `LIMIT`/`OFFSET` as written.

`plan()` itself still honours them: `ignore_pagination` defaults to `False`, so
`datum_sql` on its own means what SQL means.

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
