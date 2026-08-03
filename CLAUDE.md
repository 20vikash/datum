# Agent Guide

Datum is the telemetry service for the Frappe fleet. Producers push numbers, VictoriaMetrics
stores them, and consumers read them back over SQL or PromQL.

## Main Rules

- **VictoriaMetrics is the only storage engine that ships.** There is one escape hatch and it is
  narrow: `MetricProvider` in `datum/api/internals/providers/base.py`. Supporting another store
  means writing a provider and registering it — never widening the interface, never branching on
  the backend anywhere else in the service. If a change needs to know which provider is in use
  outside `providers/`, it is the wrong change.
- **A provider stores and retrieves. It does not query.** Selector translation lives in
  `datum_sql`, row shaping in `datum_sql.shape()`. A provider that starts interpreting SQL is a
  second query engine, which is what the seam exists to prevent.
- **There is no queue.** Producers POST to the API, the API writes to VictoriaMetrics. Do not
  reintroduce Redis, a consumer process, or a spool file.
- **Numbers only.** Datum stores metrics. Slow queries, request traces, and anything with free
  text belong somewhere else.
- **`datum_sql` is a standalone package.** It must never import from the service, and must stay
  installable and useful on its own against any Prometheus-compatible store.
- Keep API routes thin. Behaviour lives in modules the routes call.
- Group related files in folders rather than adding many same-prefix modules.
- Keep comments short. Remove comments that restate the code.
- No comment block at the top of a file. Use a short class or method docstring instead.
- Do not create or commit plan or planning markdown files.

## What Exists Today

- `datum_sql/` — SQL to PromQL translator. Pure: it opens no sockets.
  - `spec.py` — `QuerySpec`, `Matcher`, `UnsupportedSQL`
  - `planner.py` — SQL to `QuerySpec`; `_translate_predicate` is where every WHERE branch is decided
  - `rows.py` — `shape()`, `Result`; projection, ORDER BY and LIMIT over rows the caller fetched
- `datum/` — the service.
  - `config.py` — `Settings.from_env()`; `DATUM_BACKEND` picks the provider
  - `api/app.py` — `create_app(settings, tokens)`; builds the provider once, at startup
  - `api/dependencies.py` — `Store`, `Caller`
  - `api/errors.py` — validation failures that survive being serialised
  - `api/routes/v1/` — thin routes; auth is attached to the whole `/v1` mount
  - `api/internals/schemas.py` — the published wire contract
  - `api/internals/auth.py` — `Identity` (and what it stamps), `TokenStore`, `LabelConflict`
  - `api/internals/store.py` — `MetricStore`, the facade routes call
  - `api/internals/providers/` — `MetricProvider`, the registry, `VictoriaMetricsProvider`
- `tests/conftest.py` — authenticated and anonymous clients
- `tests/test_planner.py`, `test_rows.py` — translation and row shaping
- `tests/test_api.py`, `test_ingest_contract.py`, `test_auth.py`, `test_providers.py`

Every provider method is still unwritten. Four endpoints answer 501 until they land.

## Planned Layout

- `datum/beacon/` — rule evaluation and alert delivery. A second process, and it needs a provider
  too, so anything it shares with the API belongs beside the provider rather than inside `api/`.

## Shape

```
producers ──POST /v1/ingest──▶ datum-api ──▶ MetricProvider ──▶ VictoriaMetrics
                                                   ▲                    ▲
                              datum-beacon ────────┤ evaluates rules    │ the only
                                                   │                    │ one shipped
                              Insights ────────────┘ via datum_sql
```

Two processes: `datum-api` and `datum-beacon`. Nothing between the API and storage but the
provider, which is one indirection and holds no logic of its own.

## Design Expectations

- One SELECT becomes one PromQL query. If a query needs two, refuse it by name rather than
  guessing — see `REFUSED` in `planner.py`.
- Push down what reduces bytes fetched: metric name, time window, label matchers. Everything else
  is the caller's problem, deliberately.
- Every query gets a time window. Unbounded means one hour, never all of retention.
- Identity comes from the token, never the request body. Token labels are enforced, not merged: a
  body claiming a label its token already fixes is a 400.
- Auth attaches to the `/v1` mount, not to individual routes, so a new route is authenticated by
  default. It resolves before validation, so a stranger sending nonsense gets 401 and learns
  nothing about the schema.
- A second storage engine is a new file in `providers/` and one `register()` call. If it needs
  anything else, the seam is wrong and that is the bug to fix.

## Facts That Constrain Design

Measured on 8 vCPU / 15.7 GB, and worth not rediscovering:

- VictoriaMetrics absorbs 633k rows/s at 76 rows per request across 64 connections, zero errors.
  Small frequent writes are fine; this is why there is no queue.
- It reserves 60% of RAM for caches by default. Cap it with `-memory.allowedPercent`, and note
  that the percentage applies to the cgroup limit when one exists, not host RAM.
- Storage runs about 3.1 bytes per sample.
- Filtering on a label is an index hit. Filtering on `value` is impossible in a selector.
- `query_range` resamples onto a fixed grid and carries values forward — 9 stored samples came
  back as 114 rows. Use raw mode when the caller wants what is stored.
- Losing VictoriaMetrics loses in-flight data. That is accepted. If durability is ever needed,
  add `vmagent` rather than building a queue.

## Code Taste

- Choose clean code over clever code.
- Prefer explicit config over implicit behaviour.
- Keep functions small. Around 25 lines is a target, not a reason to split readable blocks.
- Keep cyclomatic complexity <= 8.
- Keep files between 100 and 500 lines when practical.
- Avoid abbreviations.
- Use standard APIs and existing helpers before adding custom logic.
- Delete before adding when existing code can be simplified.
- Fail loudly near the bug. Do not hide a bad translation behind a fallback that returns rows.
- For a no-argument method returning one noun-like value, use `@property`.
- For methods with arguments or multi-step work, use `get_<what_it_returns>()`.
- Name boolean-returning members with `is_` or `has_`.
- Default to public methods. Use a leading underscore for raw parsing, security-sensitive
  validation, or genuinely internal details.
- Always add or update tests for behaviour changes, and make sure they pass.

## Working Rules

- The environment is managed by `uv`. Use `uv run`, `uv add`, `uv sync`.
- Run `uv run pytest` and `uv run ruff check .` after changes.
- A translation change needs a test in `tests/test_planner.py` asserting the exact PromQL string.
- Verify against a real server with `uv run python tests/live_check.py <url>` before believing a
  translation works. An empty PromQL result is fast and reports success.
- For bug fixes, identify the root cause before attempting a fix.

## Docs

Keep `README.md` current with the SQL to PromQL mapping table. It is the first thing a user of
`datum_sql` reads, and the mapping is the whole contract.
