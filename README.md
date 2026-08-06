# datum

Datum stores numbers about your fleet. Producers push them in. You read them
back with SQL.

ClickHouse stores everything. Datum is the door in front of it:

```
producers (JSON)          ──┐
agents    (remote write)  ──┴──> datum ──> ClickHouse
                                             ▲
readers   (SQL)           ──> datum ─────────┤
Insights  (SQL)           ────────────────────┘  its own read-only account
```

Every call carries the same JWT. Insights does not go through datum at all — it
connects to ClickHouse directly with a read-only user, which is the point of
storing in something that already speaks SQL.

Nothing queues or buffers. If ClickHouse is down, a write fails and the producer
moves on.

---

# The service

## Endpoints

Everything real lives under `/v1`. `/health` does not, so a future `/v2` cannot
break a health check.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/v1/ingest` | JSON samples in, `{"accepted": n}` out |
| `POST` | `/v1/ingest/remote` | Prometheus remote write, `204` out |
| `POST` | `/v1/query` | SQL in, rows out |
| `GET` | `/v1/metrics` | every metric name stored |
| `GET` | `/v1/metrics/{metric}/columns` | its columns, with labels flattened |
| `GET` | `/health` | liveness |

Browse them at `/docs`. Raw schema at `/v1/openapi.json`.

## The table

One table holds everything:

```sql
CREATE TABLE datum.samples
(
    ts          DateTime64(3, 'UTC') CODEC(Delta, ZSTD),
    metric      LowCardinality(String),
    resource_id LowCardinality(String),
    labels      Map(LowCardinality(String), String),
    value       Float64 CODEC(Gorilla, ZSTD)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (resource_id, metric, ts)
```

`resource_id` is a real column rather than a key in `labels` because it is the
tenant boundary, and a boundary has to be a sort key. Every other label stays
open-ended in the map, so a producer can add one without a migration.

There is no TTL. Nothing expires on its own.

The API creates this at startup when it is missing, so it needs DDL rights the
first time it runs. It is written down once, in `datum/config/clickhouse.py`.

## Sending data

```bash
curl -X POST http://localhost:8000/v1/ingest \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"samples": [
        {"metric": "system_cpu_percent",
         "value": 12.5,
         "ts": "2026-08-05T10:00:00Z",
         "labels": {"host": "a"}}]}'
```

Up to 10,000 samples per batch. Metric and label names must match
`^[a-zA-Z_][a-zA-Z0-9_]*$` — datum refuses a bad name rather than storing
something nobody can query. That rule also refuses Prometheus names containing
`:`, which recording rules produce.

Producers that have numbers in hand and no agent should use
[`datum_client`](datum_client/README.md), which builds the names, checks the
labels and sends the batch.

There is no `resource_id` field in the body. It is not overridden, it is not
accepted: the token is the only thing that can say who a row belongs to. A
`resource_id` smuggled into `labels` is dropped.

### Prometheus remote write

Point vmagent, Prometheus or the OTel collector at `/v1/ingest/remote`:

```yaml
remote_write:
  - url: http://localhost:8000/v1/ingest/remote
    authorization:
      credentials: YOUR_JWT
```

Snappy-compressed protobuf, v1 only — the version everything sends by default.
A v2 request is refused with a 415 naming the reason rather than half-decoded,
because v2 interns its strings in a symbols table that a v1 reader would
silently mangle. `__name__` becomes the metric; the rest become labels; the
token still decides `resource_id`.

Answers `204` with an empty body, which is what remote write clients expect —
they retry anything else.

The same 10,000 sample cap applies, counted across every series in the request.
Over it the answer is `413` and nothing is stored. An agent will retry the same
oversized batch, so lower its `max_samples_per_send` rather than waiting for it
to drain.

## Reading data

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"sql": "SELECT ts, value FROM datum.samples WHERE metric = '"'"'cpu'"'"' ORDER BY ts DESC LIMIT 10"}'
```

The SQL is ClickHouse SQL and it is passed through as written. There is no
translator, and datum refuses no query of its own. What constrains a read is
applied by ClickHouse: `readonly=1`, so a query route cannot mutate even if the
credential could, plus a row cap and an execution timeout. When the cap is hit
the answer comes back with `"truncated": true` rather than silently short.

**A read only ever sees the token's own `resource_id`**, and two things enforce
it. Together they are the tenant boundary; either one alone has a hole.

1. **A row policy on the table**, reading a per-request custom setting:

   ```sql
   CREATE ROW POLICY OR REPLACE tenant ON datum.samples
   USING resource_id = getSetting('SQL_datum_resource_id')
   TO datum;
   ```

   This binds to the *table*, so it holds however the rows are reached —
   including `merge()`, which reads the same rows under a different name. datum
   creates it in `ensure_schema` alongside the table, because a deployment with
   the table but no policy reads across tenants.

2. **Grants**, which decide what else the credential can see at all. Without them
   `system.query_log` hands over other tenants' SQL and `url()` fetches from the
   ClickHouse host.

`additional_table_filters` was a third layer and was removed: on ClickHouse 26.7
it is applied after projection, so every query that did not select `resource_id`
failed with `NOT_FOUND_COLUMN_IN_BLOCK`. It also only ever bound to the name
written in the query, which is the weakness the row policy exists to cover.

`readonly=1` is what stops a caller resetting the setting from inside their own
SQL. `/metrics` and `/metrics/{metric}/columns` are scoped the same way, so a
leaked read token cannot even enumerate another machine's metric names.

Measured in production on ClickHouse 26.7 as `pilot-staging`, with two tenants
present: a direct read, a subquery, a union, `merge('datum', '^samples$')` and
`count()` all returned that tenant and nothing else; `remote()`,
`system.query_log`, and overriding the setting in SQL were all refused.

### Capping request bodies

datum does not cap the raw body itself; the reverse proxy does. Every limit in
`config/limits.py` is reached *after* the body is read, so without a proxy limit
a large POST is resident before anything checks it. The datum vhost sets:

```nginx
client_max_body_size 32m;
```

Keep that line. A deployment that drops it has no bound on a request body at
all, and datum listens on `127.0.0.1:8000`, so anything reaching the port
directly is likewise uncapped.

### Setting the ClickHouse side up

The custom setting needs a server-side prefix, or **every read fails** — loudly,
not silently, but it fails. In `config.d/datum.xml`:

```xml
<clickhouse>
    <custom_settings_prefixes>SQL_</custom_settings_prefixes>
</clickhouse>
```

Then the API's user, granted only what it uses:

```sql
CREATE USER datum IDENTIFIED BY '...';
REVOKE ALL ON *.* FROM datum;
GRANT SELECT, INSERT ON datum.samples TO datum;
GRANT CREATE DATABASE, CREATE TABLE ON datum.* TO datum;
GRANT CREATE ROW POLICY ON datum.* TO datum;
```

The last two are what `ensure_schema` needs. The revoke is the important line:
it is what removes `system.*` and the `remote`/`url`/`file`/`s3` table
functions, and no filter substitutes for it.

**datum checks this at startup and refuses to run without it.** `ensure_schema`
reads `SHOW GRANTS FOR CURRENT_USER` and stops if the credential holds anything
beyond `datum.samples` and `datum.*`, naming the grant. It checks rather than
applies: revoking its own grants would mean holding `GRANT OPTION` on them, and
a credential that can narrow itself can widen itself again.

So a deployment that skips the revoke fails loudly on boot rather than serving
reads that can walk out through `system.*`.

Insights reads with its **own** user and is deliberately outside the policy —
`TO datum` names the API's user only, so the BI path still sees the fleet.

## Tokens

Every call carries a JWT that Central signed: `Authorization: Bearer <jwt>`.

```json
{
  "resource_id": "vm-abc123",
  "access": ["read", "write"]
}
```

**`access` says what the token may do.** Central signs bench logins, site logins
and enrolment tokens with the same key; without this, any of them would be
accepted here. A token that claims neither gets a 403 on every route.

**`resource_id` says where the metrics came from**, and it is the only label the
token carries. One machine, one id. Everything else — which team owns it, which
cluster it sits in — is Central's to answer, not a label on every sample. It is
required: writes are stamped with it and reads are scoped by it, so a token
without one is a 401 rather than a caller whose access is then judged.

Signatures must be RSA or ECDSA. HMAC is never accepted.

## What each status means

| Status | Meaning |
|---|---|
| 200 | answered, or stored |
| 204 | stored, via remote write |
| 400 | ClickHouse refused the query, or the remote write body was unreadable |
| 401 | JWT missing, unsigned, expired, signed by the wrong key, or naming no `resource_id` |
| 403 | the token may not do that: no `read`, or no `write` |
| 413 | decompressing past 12 MB, more than 10,000 samples or series, or a series wider than 64 labels |
| 415 | remote write v2, which is not read here |
| 422 | the request body broke the schema |
| 503 | datum is up, ClickHouse is not |

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `DATUM_CLICKHOUSE_HOST` | required | where ClickHouse is |
| `DATUM_CLICKHOUSE_PORT` | `8123` | its HTTP port |
| `DATUM_CLICKHOUSE_USER` | `default` | needs SELECT and INSERT, nothing more |
| `DATUM_CLICKHOUSE_PASSWORD` | empty | |
| `DATUM_CLICKHOUSE_DATABASE` | `datum` | |
| `DATUM_CLICKHOUSE_TABLE` | `samples` | |
| `DATUM_MAX_ROWS` | `100000` | cap on one read |
| `DATUM_TIMEOUT` | `30` | seconds, connect and execute |
| `DATUM_JWT_PUBLIC_KEY_FILE` | none | the PEM file to check tokens against |
| `DATUM_OIDC_ISSUER` | none | fetch keys from an issuer instead. With neither, every call is a 401 |

## Running it

```bash
docker run -d --name clickhouse -p 8123:8123 clickhouse/clickhouse-server

mkdir -p .dev
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out .dev/central.key
openssl rsa -in .dev/central.key -pubout -out .dev/central.pub
chmod 600 .dev/central.key

uv sync --all-groups
DATUM_CLICKHOUSE_HOST=127.0.0.1 DATUM_JWT_PUBLIC_KEY_FILE=.dev/central.pub \
  uv run uvicorn datum.api.app:create_app --factory --port 8000
```

`.dev/` is gitignored, so the test key cannot be committed by accident.

Then mint a token and use it:

```bash
JWT=$(uv run --with 'pyjwt[crypto]' python -c "
import jwt, time
from pathlib import Path
print(jwt.encode({'exp': int(time.time())+3600,
  'resource_id': 'vm-abc123', 'access': ['read', 'write']},
  Path('.dev/central.key').read_text(), algorithm='RS256'))")
```

Tokens last an hour. An expired one gives 401 and looks exactly like a wrong
key, so make a fresh one before hunting for a bug.

There is no installer. datum-api is one process; run it under whatever already
supervises your services, and install ClickHouse the way its own docs say.

## Working on it

```bash
uv run pytest
uv run ruff check .
```

The remote write message is generated. Change `remote_write.proto` and run:

```bash
uv run --with grpcio-tools python -m grpc_tools.protoc \
  -Idatum/api/internals/remote --python_out=datum/api/internals/remote \
  datum/api/internals/remote/remote_write.proto
```
