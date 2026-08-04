# datum_client

Push metrics to Datum without writing HTTP, and without inventing metric names.

Standard library only. It imports nothing from the Datum service, so a producer
can install it and never pull in `sqlglot` or FastAPI.

```python
from datum_client import Batch, Datum

datum = Datum("https://datum.internal", token=DATUM_TOKEN)

system = Batch("system")
system.gauge("load_average", 0.42, window="1m")

memory = Batch("system", "memory")
memory.gauge("used", 1154545090, "bytes")

datum.send(system, memory)          # separate batches, one POST
```

## What a Batch is

A `Batch` collects samples that share a namespace, a subsystem and some labels.
It is not one sample, and not necessarily one request — `send` takes as many
batches as you like and posts them together.

One collection tick should be one `send`. Twenty-four separate sends would be
twenty-four chances to block that tick.

```
Batch("pilot", "process", bench="bench_0001")
  │      │         │              └─ label on every sample in this batch
  │      │         └─ subsystem
  │      └─ namespace
  └─ each gauge/counter/up/info call adds one sample

send(batch, other_batch, ...)  ->  all their samples  ->  1 POST
```

## Naming

Names are built for you, as `namespace_subsystem_target_unit_suffix`, with
empty parts dropped:

```python
batch = Batch("pilot", "process", bench="bench_0001")

batch.gauge("cpu", 1.2, "percent", service="web")
# pilot_process_cpu_percent{bench="bench_0001",service="web"} 1.2

batch.counter("io_read", 4096, "bytes", service="web")
# pilot_process_io_read_bytes_total{...} 4096
```

Because `namespace` and `subsystem` live on the batch, call sites pass only what
varies. That does more for consistency than validation does.

| Method | Suffix | Use for |
|---|---|---|
| `gauge` | none | a value that rises and falls: a percentage, a size, a depth |
| `counter` | `_total` | a value that only climbs, so PromQL can `rate()` it |
| `up` | `_up` | 1 alive, 0 dead — see below |
| `info` | `_info` | always 1, carrying facts as labels |

A batch has one subsystem. A record spanning several means several batches,
handed to `send` together so it stays one request:

```python
memory = Batch("system", "memory")
memory.gauge("used", used_bytes, "bytes")     # system_memory_used_bytes

cpu = Batch("system", "cpu")
cpu.gauge("usage", 12.5, "percent")           # system_cpu_usage_percent

datum.send(memory, cpu)
```

They stay separate objects on purpose: nothing can append to another batch's
samples by accident, and a process batch can never write into a system one.

## Units

The unit is appended to the name, the same way `prometheus_client` does it:

```python
memory.gauge("used", 1154545090, "bytes")     # system_memory_used_bytes
timing.gauge("request", 0.42, "seconds")      # system_request_seconds
```

It is **not validated**. Any unit string is accepted and becomes part of the
name, so `gauge("used", 1967.64, "mb")` gives you `system_memory_used_mb`.

Prometheus convention is base units — `bytes`, `seconds`, `ratio` (and
`percent`, widely used) — because a scaled unit puts a hidden factor into every
query and alert threshold that follows, and a stored name cannot be corrected
later. Nothing enforces it. Convert at the call site:

```python
memory.gauge("used", record["used_mb"] * 1024 * 1024, "bytes")
timing.gauge("request", elapsed_ms / 1000, "seconds")
```

Unitless is fine when a unit would say nothing — a load average is a count of
runnable processes, not a quantity of anything:

```python
batch.gauge("load_average", 0.42, window="1m")     # system_load_average
```

The unit is not appended twice if the target already ends with it:

```python
batch.gauge("memory_rss", 1024, "bytes")        # pilot_process_memory_rss_bytes
batch.gauge("memory_rss_bytes", 1024, "bytes")  # pilot_process_memory_rss_bytes
```

Units still have to be valid *name* characters, so `MB` and `MiB` are refused
for being uppercase, not for being scaled.

## Labels that would kill the store

`pid`, `container_id`, `request_id`, `trace_id` and `uuid` change constantly. As
a label, each new value is a **new series**, permanently. A pid on eight metrics
across every restart, service and host is how a metrics store dies.

```python
batch.gauge("cpu", 1.2, "percent", pid="4412")
# BadName: 'pid' changes constantly, so it would make a new series each time.
#          Label by service instead, and put it on an _info metric.

batch.info("", service="web", pid="4412")     # allowed here, and only here
# pilot_process_info{service="web",pid="4412"} 1
```

`_info` confines the churn to one series instead of eight. It does not remove
it — if nothing queries by pid, leaving it out is cheaper.

Label names follow the metric rule: lowercase, underscores, no dots or dashes.

## Report absence, don't omit it

A missing series is invisible on a dashboard. A zero is alertable.

```python
for service, pid in targets.items():
    alive = pid is not None
    batch.up("", alive, service=service)
    if not alive:
        continue
    batch.gauge("cpu", cpu_percent(pid), "percent", service=service)
```

Same reason a failed scrape emits `scrape_up 0` rather than nothing.

## Strings are not numbers

Datum stores numbers. Encode a state as a label on a metric that is always 1:

```python
batch.gauge("state", 1, service="web", state="S")
# pilot_process_state{service="web",state="S"} 1
```

Then `pilot_process_state{state="Z"} == 1` finds zombies.

## Timestamps

Every sample needs one and Datum will not invent it — a server clock records
arrival, not observation, which skews the moment a batch is delayed.

The client fills in `datetime.now(UTC)` per sample, which is producer time and
therefore correct. Pass `ts=` to use the moment the reading was actually taken:

```python
taken = datetime.fromisoformat(record["time"])
batch.gauge("cpu", record["cpu_percent"], "percent", ts=taken)
```

For one record, pass the same `ts` to every sample so they line up as one tick.

Stored to millisecond precision, so a round trip loses sub-millisecond detail.

## Sending

```python
status = datum.send(batch)
status = datum.send(system, memory, cpu)      # still one POST
```

Fire and forget: one POST, a 2 second timeout, no spool and no retry. A dropped
metric is a gap in a chart; blocking a producer to retry it is worse.

- **`send` never raises on a network failure.** Unreachable returns `0`.
- **It returns the HTTP status** so you can notice `401` or `422`, which are
  bugs rather than blips. Both are logged at WARNING on the `datum` logger.

Silence is the failure mode that hurts: an expired token 401s, metrics stop, and
the config still looks right. Check the status, or make sure a dead-man's-switch
rule covers the source.

| Status | Meaning |
|---|---|
| 202 | accepted |
| 400 | a label the token already fixes was sent in the body |
| 401 | unknown or missing token |
| 422 | a sample broke the contract; the body names the field and index |
| 503 | Datum is up, the store is not |
| 0 | never landed |

## Identity comes from the token

Never send `tenant_id`, `source_id`, or any label the token already fixes —
those are refused. Datum stamps them on for you, which is what stops one host
claiming to be another.

```python
batch.gauge("cpu", 1.2, "percent", service="web")
# stored as:
# pilot_process_cpu_percent{service="web",region="ap_south_1",
#                           tenant_id="acme",source_id="pilot_1"} 1.2
```

## Limits

| Limit | Value |
|---|---|
| samples per batch | 10 000 |
| labels per sample | 30 |
| label value length | 256 |
| metric name length | 200 |

Values must be finite: `NaN` and `Inf` are refused.

There is **no body size limit** yet. The 10 000 sample cap is the only thing
bounding a request, and it is enforced after the body has been read, so a large
one is buffered before being refused.
