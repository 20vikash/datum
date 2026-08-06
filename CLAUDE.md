# Agent Guide

Datum is the telemetry service for the Frappe fleet. Producers push numbers at the API,
ClickHouse stores them, and consumers read them back with SQL.

## Main Rules

- **ClickHouse is the only storage engine that ships.** There is one escape hatch and it is
  narrow: `MetricProvider` in `datum/api/internals/providers/base.py`. Supporting another store
  means writing a provider and pointing `app.py` at it — never widening the interface, never
  branching on the backend anywhere else in the service. There is no registry and no
  `DATUM_BACKEND`: selecting between engines was cost with no buyer.
- **A provider carries no logic.** It runs the SQL it is handed and writes the rows it is
  handed. There is no facade over it: routes depend on `MetricProvider` directly.
- **There are two write paths, and they build rows differently on purpose.** JSON goes through
  `Sample`, which validates and renders itself with `get_row(resource_id)`. Remote write does
  not: a metric and its labels belong to the series, so `decode` checks them once per series
  and builds rows directly, rather than validating the same strings once per reading. The cost
  is that `NAME` is enforced in two places — `schemas.Sample` and `remote._series`. Change the
  name rule and you change both, or the paths disagree about what is storable.
- **Reads are passed through, not translated.** ClickHouse speaks SQL, so datum does not
  interpret it. There is no planner and no refusal list. What constrains a read is applied by
  ClickHouse — `readonly=1`, a row cap, a timeout — never by parsing SQL in Python. Every read
  takes a `resource_id`, not just `/query`: metric and label listings are the same table.
- **The tenant boundary is three things, and none of them is Python.** A row policy reading
  `RESOURCE_SETTING` binds to the table, so it holds however the rows are reached;
  `additional_table_filters` binds to the name in the query and is the backstop;
  grants decide what the credential can reach at all. `merge('datum', '^samples$')` defeats
  the second and not the first — that is measured, not assumed, and it is why both exist.
  The policy is created in `ensure_schema`, because a table without it is a table that leaks.
  Grants are *checked* there too, never applied: a credential that can narrow itself can widen
  itself again, so datum reads `SHOW GRANTS` and refuses to start on anything wider.
- **Numbers only.** Datum stores metrics. Slow queries, request traces, and anything with free
  text belong somewhere else.
- **Insights connects to ClickHouse directly**, with its own read-only user. `/v1/query` exists
  for callers that are not Insights. Do not build a BI integration through the API.
- Keep API routes thin. Behaviour lives in modules the routes call — but do not add a layer
  that only forwards. A facade earns its place by holding logic, not by existing.
- Group related files in folders rather than adding many same-prefix modules.
- Keep comments short. Remove comments that restate the code.
- No comment block at the top of a file. Use a short class or method docstring instead.
- Do not create or commit plan or planning markdown files.

## What Exists Today

- `datum/` — the service.
  - `config/` — every default lives here, nothing hardcoded elsewhere
    - `api.py` — `Settings.from_env()`; how to reach ClickHouse, and identifier checking
    - `clickhouse.py` — the one table's DDL, its column order, and `resource_id`'s name
    - `limits.py` — every cap on one request, in the order a request meets them
  - `api/app.py` — `create_app(settings, tokens, provider)`; builds the provider once, at
    startup, and creates the schema if it is missing
  - `api/middleware.py` — `BodyLimit`; the only cap that runs before an allocation
  - `api/dependencies.py` — `Provider`, `Caller`, `Reader`, `Writer`; the gates on `/v1`
  - `api/errors.py` — every failure a caller can cause, mapped to its status
  - `api/routes/v1/` — `query.py` and `ingest.py`, mounted in `v1/__init__.py`
  - `api/internals/schemas.py` — the published wire contract, and `Sample.get_row`
  - `api/internals/auth.py` — `Identity`, `TokenVerifier`; JWT signature checking
  - `api/internals/providers/` — `MetricProvider` and `ClickHouseProvider`
  - `api/internals/remote/` — Prometheus remote write v1: snappy off, protobuf out, rows in.
    `decode(body, resource_id)` returns table rows, not `Sample`s. The `_pb2.py` is generated;
    regenerate it rather than editing it, and ruff skips it
- `datum_client/` — what producers import. Standard library only, and it must never import from
  the service.
- `tests/conftest.py` — a fixed test keypair, a `FakeProvider`, and authenticated and
  anonymous clients
- `tests/test_api.py`, `test_ingest.py`, `test_remote_write.py`, `test_providers.py`
- `tests/test_auth.py`, `test_key_loading.py`, `test_oidc.py`

There is no installer and no systemd unit. datum-api is one process, run however the host
already runs things; ClickHouse is installed the way its own docs say.

## Shape

```
producers ──JWT──▶ datum-api ──▶ ClickHouse
                        ▲             ▲
Insights ───────────────┼─────────────┘ read-only user, direct
                        │
datum-beacon ───────────┘ evaluates rules
```

## Planned Layout

- `datum/beacon/` — rule evaluation and alert delivery. A second process, and it needs a
  provider too, so anything it shares with the API belongs beside the provider rather than
  inside `api/`.

## Design Expectations

- **Identity comes from the token, never the request body.** The token carries `resource_id`,
  which datum stamps on every row and scopes every read to, and `access`, which says whether it
  may read, write or both. A `resource_id` in the body is dropped, not honoured, and there is
  no field for it in the wire schema. `resource_id` is required: a token without one resolves
  to no `Identity` at all, so it is a 401, not a 403.
- One label, not a set. Which team owns a machine, or which cluster it sits in, is Central's to
  answer; putting it on every sample makes it a fact frozen at write time.
- Signatures are RSA or ECDSA. HMAC is never accepted.
- Auth attaches to the `/v1` mount, not to individual routes, so a new route is authenticated
  by default. It resolves before validation, so a stranger sending nonsense gets 401 and learns
  nothing about the schema.
- What a token may *do* is asked for by name: a route takes `Reader` or `Writer` as an
  argument. Both are visible in the signature, so a route never gets its permissions from
  somewhere else in the file tree. A new route that asks for neither is authenticated but
  ungated — read the signature.
- A second storage engine is a new file in `providers/` and one changed line in `app.py`. If it
  needs anything else, the seam is wrong and that is the bug to fix.
- Fail loudly and near the bug. An unreachable store is a 503, a query ClickHouse refused is a
  400, and neither is ever an empty result set.

## Facts That Constrain Design

- The table is `ORDER BY (resource_id, metric, ts)`. A read that filters on none of those scans
  everything; that is the cost of one wide table, and the right trade for a fleet whose queries
  always name a machine.
- `labels` is a `Map`. Filtering on a map key is not an index hit the way a sort key is. If a
  label becomes hot enough to matter, promote it to a column rather than adding an index.
- `Delta` on the timestamp and `Gorilla` on the value are doing most of the compression. Do not
  drop the codecs.
- There is no TTL. Nothing expires on its own, so cardinality is a permanent cost, not one that
  retention eventually clears.
- Losing ClickHouse loses in-flight data. That is accepted. There is no queue, no spool file
  and no retry, because blocking a producer's collection tick is worse than a gap in a chart.

## Code Taste

- Choose clean code over clever code.
- Prefer explicit config over implicit behaviour.
- Keep functions small. Around 25 lines is a target, not a reason to split readable blocks.
- Keep cyclomatic complexity <= 8.
- Keep files between 100 and 500 lines when practical.
- Avoid abbreviations.
- Use standard APIs and existing helpers before adding custom logic. Reach for a library before
  hand-rolling a parser.
- Delete before adding when existing code can be simplified.
- For a no-argument method returning one noun-like value, use `@property`.
- For methods with arguments or multi-step work, use `get_<what_it_returns>()`.
- Name boolean-returning members with `is_`, `has_` or `can_`.
- Default to public methods. Use a leading underscore for raw parsing, security-sensitive
  validation, or genuinely internal details.
- Always add or update tests for behaviour changes, and make sure they pass.

## Working Rules

- The environment is managed by `uv`. Use `uv run`, `uv add`, `uv sync`.
- Run `uv run pytest` and `uv run ruff check .` after changes.
- A schema change needs a matching change in `COLUMNS`, and a test asserting the insert order.
- Every cap lives in `config/limits.py`, and they are a ladder, not alternatives. `MAX_BODY` is
  the only one that runs before an allocation, so it is what makes the rest affordable;
  `MAX_DECOMPRESSED` bounds what snappy expands to, which the body cap cannot see;
  `MAX_BATCH` bounds what ClickHouse is asked to swallow, and is reached only after a parse.
  Adding a cap means adding it there and saying which of those three it is.
- **Remote write counts series before it parses.** `MAX_BATCH` counts readings, so a body of
  series carrying none passes it: 987k empty series cost 0.8 MB on the wire and measured
  191 MB parsed. `_count_series` walks the top-level protobuf tags, allocates nothing and
  stops early. A series always holds at least one reading, so `MAX_BATCH` bounds series too.
- Construction must open no sockets. The provider connects on first use, so tests and startup
  do not depend on ClickHouse being up.
- Routes are `def`, not `async def`. Every store call blocks, so it belongs in the threadpool
  rather than on the event loop; take a raw body with `Body`, never `await request.body()`.
- For bug fixes, identify the root cause before attempting a fix.

## Docs

Keep `README.md` current: the endpoint table, the table definition and the token claims are the
whole contract, and they are the first thing a user reads.
