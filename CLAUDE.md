# Agent Guide

Datum is the telemetry service for the Frappe fleet. Producers push numbers through vmauth,
VictoriaMetrics stores them, and consumers read them back over SQL.

## Main Rules

- **VictoriaMetrics is the only storage engine that ships.** There is one escape hatch and it is
  narrow: `MetricProvider` in `datum/api/internals/providers/base.py`. Supporting another store
  means writing a provider and pointing `app.py` at it — never widening the interface, never
  branching on the backend anywhere else in the service. There is no registry and no
  `DATUM_BACKEND`: selecting between engines was cost with no buyer.
- **A provider retrieves. It does not query, and it does not write.** Selector translation lives in
  `datum_sql`, row shaping in `datum_sql.shape()`. A provider that starts interpreting SQL is a
  second query engine, which is what the seam exists to prevent.
- **There is no queue, and no write path in Python.** Producers POST to vmauth, which verifies
  the JWT and proxies to VictoriaMetrics. Do not reintroduce Redis, a consumer process, a spool
  file, or an ingest route on the API.
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
  - `config/` — every default and every generated file lives here, nothing hardcoded elsewhere
    - `api.py` — `Settings.from_env()`; the store URL, read from the unit's `Environment=`
    - `victoria.py` — retention, memory, the cardinality limiter
    - `units.py` — the systemd units, and where the API listens
    - `paths.py` — where generated files and logs go
    - `vmauth.py` — `VmauthSettings` and the generated `-auth.config`
  - `api/app.py` — `create_app(settings, tokens)`; builds the provider once, at startup
  - `api/dependencies.py` — `Store`, and `get_identity`, the gate on the `/v1` mount
  - `api/errors.py` — validation failures that survive being serialised
  - `api/routes/` — thin routes, reads only; `/v1` and the auth gate are attached in one
    `include_router` call, so a new route is versioned and authenticated without saying so
  - `api/internals/schemas.py` — the published wire contract
  - `api/internals/auth.py` — `Identity`, `TokenVerifier`; JWT signature checking
  - `api/internals/store.py` — `MetricStore`, the facade routes call
  - `api/internals/providers/` — `MetricProvider` and `VictoriaMetricsProvider`. Reads only
  - `setup/` — putting the above on a host. `bootstrap.py` at the root is nineteen lines that
    call into it.
    - `options.py` — `Options`, the parsed command line, already resolved and checked
    - `installer.py` — `Installer`; renders, writes, and hands the changed set to systemd
    - `systemd.py` — `Systemd`, the only part that needs Linux
- There is no env file: units carry what they need and the public key stays a file both vmauth
  and datum-api read, so the two cannot verify against different keys. `--config-only` skips
  systemd entirely, which is how the stack runs on a Mac.
- `tests/conftest.py` — a fixed test keypair, and authenticated and anonymous clients
- `tests/test_planner.py`, `test_rows.py` — translation and row shaping
- `tests/test_api.py`, `test_auth.py`, `test_key_loading.py`, `test_oidc.py`, `test_providers.py`
- `tests/test_bootstrap.py`, `test_vmauth_config.py` — what gets generated

The vmauth config is the write path's whole security boundary, so `test_vmauth_config.py` asserts
its exact text rather than its shape. Local development lives in `.dev/`, which is gitignored so a
test private key cannot be committed.

`MetricProvider` retrieves only. Nothing in this service writes samples.

## Planned Layout

- `datum/beacon/` — rule evaluation and alert delivery. A second process, and it needs a provider
  too, so anything it shares with the API belongs beside the provider rather than inside `api/`.

## Shape

```
producers ──JWT──▶ vmauth ──extra_label──▶ VictoriaMetrics
                                                 ▲
                     datum-api ──▶ MetricProvider┤ reads only
                          ▲                      │
                     Insights ── via datum_sql   │
                                                 │
                     datum-beacon ───────────────┘ evaluates rules
```

Three processes: `vmauth`, `datum-api` and `datum-beacon`. Writes never reach Python. Between a
read and storage there is nothing but the provider, which holds no logic of its own.

## Design Expectations

- One SELECT becomes one PromQL query. If a query needs two, refuse it by name rather than
  guessing — see `REFUSED` in `planner.py`.
- Push down what reduces bytes fetched: metric name, time window, label matchers. Everything else
  is the caller's problem, deliberately.
- Every query gets a time window. Unbounded means one hour, never all of retention.
- Identity comes from the token, never the request body. On writes vmauth turns the JWT's
  `vm_access.metrics_extra_labels` into `extra_label` args and VictoriaMetrics applies them over
  whatever the body claimed, so a spoofed label loses. It is overridden, not refused — datum no
  longer sees the payload, which is the price of keeping Python out of the write path.
- Signatures are RSA or ECDSA. vmauth accepts nothing else, so datum must not either: the two
  disagreeing about what a valid token is would be the bug. The same applies to how the key is
  obtained — one `bootstrap.py` flag configures both, and `TokenVerifier` does the same discovery
  vmauth does, refreshing on the same five minutes.
- Auth attaches to the `/v1` mount, not to individual routes, so a new route is authenticated by
  default. It resolves before validation, so a stranger sending nonsense gets 401 and learns
  nothing about the schema.
- A second storage engine is a new file in `providers/` and one changed line in `app.py`. If it
  needs anything else, the seam is wrong and that is the bug to fix.

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
