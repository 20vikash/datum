# datum

Datum stores numbers about your fleet. Producers push them in. You read them
back with SQL.

Three parts:

| Part | What it is | Who uses it |
|---|---|---|
| `datum` | reads: SQL over HTTP | Insights |
| `datum_client` | what producers import to push | Pilot, agents |
| `datum_sql` | turns SQL into PromQL | the service, and Insights |

VictoriaMetrics stores everything. Two doors lead to it, and both check the
same token:

```
producers  (JSON) ─────────┐
collectors (remote write) ─┴──> vmauth ──┐
                                         ├──> VictoriaMetrics
readers    (SQL) ──────────> datum ──────┘
```

Writes never touch Python. vmauth checks the token and hands the bytes to
VictoriaMetrics, which stamps the caller's labels on the way in. Datum only
reads: it turns SQL into PromQL and asks VictoriaMetrics for the rows.

Nothing queues or buffers. If VictoriaMetrics is down, a write fails and the
producer moves on.

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

**Nothing checks your samples.** VictoriaMetrics takes what it is given, so a
metric name with a dot in it is stored rather than refused. Get the names right
in the producer — `datum_client` does that for you. What is enforced is who you
are: the token's labels always win.

## Tokens

Every call carries a JWT that Central signed: `Authorization: Bearer <jwt>`.
A token needs exactly two things:

```json
{
  "scope": "datum",
  "vm_access": {"metrics_extra_labels": ["resource_id=vm-abc123"]}
}
```

**`scope` says the token may write.** Central signs bench logins, site logins and
enrolment tokens with the same key. Without a scope to match on, any of them
would be accepted here. vmauth checks for `datum` and rejects the rest.

**`resource_id` says where the metrics came from**, and it is the only label the
token carries. One machine, one id. Everything else — which team owns it, which
cluster it sits in — is Central's to answer, not a label on every sample.

vmauth turns that into an `extra_label` query arg, and VictoriaMetrics writes it
**over** whatever your body said:

```
you send:    system_cpu_percent{host="a", resource_id="someone_else"}
gets stored: system_cpu_percent{host="a", resource_id="vm-abc123"}
```

So a producer cannot claim another machine's id. Note you get no error for
trying — the label is quietly replaced, not refused. Labels you send that the
token does not fix, like `host`, are kept.

Reads use the same token and the same key, so one token works on both doors.
Signatures must be RSA or ECDSA. vmauth cannot check HMAC, so neither does
datum: if they disagreed about what a valid token is, that would be the bug.

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

Three programs run: VictoriaMetrics stores the numbers, vmauth checks tokens on
writes, and datum answers reads. This works on a Mac — no systemd involved.

Install the two binaries. VictoriaMetrics is in Homebrew; vmauth is not, so take
it from the `vmutils` archive on the
[releases page](https://github.com/VictoriaMetrics/VictoriaMetrics/releases) and
use the same version:

```bash
brew install victoriametrics
# unpack vmutils, then:
install -m 755 vmauth-prod /opt/homebrew/bin/vmauth
```

Make a test key pair. Central will sign tokens with the private half; both
vmauth and datum check them with the public half:

```bash
mkdir -p .dev
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out .dev/central.key
openssl rsa -in .dev/central.key -pubout -out .dev/central.pub
chmod 600 .dev/central.key
```

Write the config. `--config-only` skips the systemd part and prints the three
commands to run:

```bash
uv sync --all-groups
uv run python bootstrap.py --config-only \
  --public-key .dev/central.pub --config-dir .dev --data-dir .dev/data
```

`.dev/` is gitignored, so the test key cannot be committed by accident. Run the
three printed commands in three terminals.

Now make a token and use it:

```bash
JWT=$(uv run --with 'pyjwt[crypto]' python -c "
import jwt, time
from pathlib import Path
print(jwt.encode({'exp': int(time.time())+3600,
  'scope': 'datum',
  'vm_access': {'metrics_extra_labels': ['resource_id=vm-abc123']}},
  Path('.dev/central.key').read_text(), algorithm='RS256'))")

# write, through vmauth
curl -X POST http://127.0.0.1:8427/api/v1/import -H "Authorization: Bearer $JWT" \
  -d '{"metric":{"__name__":"cpu"},"values":[7],"timestamps":['$(date +%s)'000]}'

# read, through datum
curl -X POST http://127.0.0.1:8000/v1/query -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' -d '{"sql":"SELECT * FROM cpu"}'
```

Tokens last an hour. An expired one gives 401 everywhere and looks exactly like
a wrong key, so make a fresh one before hunting for a bug.

Datum reads these from its environment:

| Variable | Default | What it does |
|---|---|---|
| `DATUM_URL` | required | where VictoriaMetrics is |
| `DATUM_JWT_PUBLIC_KEY_FILE` | none | the PEM file to check tokens against |
| `DATUM_OIDC_ISSUER` | none | fetch keys from an issuer instead. With neither, every call is a 401 |
| `DATUM_DIALECT` | `mysql` | SQL flavour the translator reads |
| `DATUM_MODE` | `raw` | `raw` or `step` |
| `DATUM_IGNORE_PAGINATION` | `1` | drop `LIMIT`/`OFFSET` sent by BI tools. `0` honours them |

`bootstrap.py` sets the first three for you. You only set them by hand if you
run uvicorn yourself.

**Keep VictoriaMetrics on `127.0.0.1`.** It has no login of its own. vmauth and
datum are what stand in front of it. Bind it to `0.0.0.0` and anyone who reaches
the port can read and write everything, no token needed.

## Putting it on a server

Linux only. Runs as your own user — no root, no sudo.

```bash
git clone https://github.com/frappe/Datum.git ~/datum
cd ~/datum && uv sync --all-groups

# save Central's public key somewhere, then:
.venv/bin/python bootstrap.py --public-key ~/services/central.pub
```

That writes the config, installs three services and starts them:

```
~/services/                     unit files and vmauth.yml, all generated
~/.config/systemd/user/         symlinks, because that is where systemd looks
~/.local/share/datum/           the metrics data
~/.local/share/datum/logs/      access.log, error.log, vmauth-*.log
```

```bash
systemctl --user status datum-api
tail -f ~/.local/share/datum/logs/access.log
```

Run it twice and nothing happens. It only restarts a service whose config
actually changed.

**There is no env file.** Each unit carries what it needs, and the public key is
a file on disk that vmauth and datum both read. They cannot end up checking
tokens against different keys.

It will not install VictoriaMetrics or vmauth for you. It checks your PATH and
tells you where to get them.

Three ways to check tokens, and you pick exactly one:

| Flag | What happens |
|---|---|
| `--public-key PATH` | both services read that PEM file |
| `--oidc-issuer URL` | both fetch keys from the issuer, refreshing every 5 minutes |
| `--skip-verify` | signatures are not checked at all. Local testing only |

Passing two of them stops the script, as does pointing `--public-key` at a file
that is not there. Neither gets past the point where anything is written.

With `--oidc-issuer`, tokens must carry an `iss` that matches the issuer
exactly. If the issuer is unreachable, reads answer 401 rather than letting
anyone through. `--skip-verify` leaves reads shut while writes are open, which
is the right shape for a testing mode.

Separately, `--scope` decides *which* tokens may write. It defaults to `datum`
and matches the token's `scope` claim, which is what keeps a bench login from
being accepted as permission to push metrics. `--scope ''` drops the check and
lets through anything Central's key signed — only useful before Central starts
minting with a scope.

Other flags: `--dry-run` prints every file without writing it, and `--help`
lists `--vmauth-listen`, `--datum-port`, `--retention`, `--config-dir`,
`--data-dir`.

**No HTTPS.** Tokens travel in plain text. Fine on loopback or a private
network. Put a TLS proxy in front before real hosts push to it.

## Swapping the storage engine

Only for reads. Writes go from vmauth straight into VictoriaMetrics and never
pass through this code, so a second engine would answer queries while writes
kept landing somewhere else. Worth knowing before you reach for this.

For reads, it plugs in through one small interface, so another engine is a new
file rather than a rewrite:

```python
from datum.api.internals.providers import MetricProvider


class ClickHouseProvider(MetricProvider):
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

datum = Datum("https://vmauth.internal:8427", token=DATUM_JWT)

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
    SELECT resource_id, ts, value
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
| `WHERE resource_id LIKE 'vm-%'` | `{resource_id=~"vm-.*"}` |
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
