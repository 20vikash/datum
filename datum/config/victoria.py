from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LISTEN = "127.0.0.1:8428"
DEFAULT_RETENTION = "12"
DEFAULT_MEMORY_PERCENT = "40"

# Cardinality limiter. `-1` counts new series and publishes the counters without
# dropping anything, because over the limit VictoriaMetrics discards silently:
# the writer still gets 204 and only vm_hourly_series_limit_rows_dropped_total
# moves. Watch those counters, then set a real number once the normal rate is
# known. See datum_client's README for why series churn is the thing to watch.
DEFAULT_HOURLY_SERIES = "-1"
DEFAULT_DAILY_SERIES = "-1"


@dataclass(frozen=True)
class VictoriaSettings:
    """How the store runs.

    `listen` stays on loopback: VictoriaMetrics has no auth of its own, so
    vmauth and the API are the only ways in. Binding it anywhere else hands
    every tenant's data to whoever reaches the port.
    """

    listen: str = DEFAULT_LISTEN
    retention: str = DEFAULT_RETENTION
    memory_percent: str = DEFAULT_MEMORY_PERCENT
    hourly_series: str = DEFAULT_HOURLY_SERIES
    daily_series: str = DEFAULT_DAILY_SERIES

    @property
    def url(self) -> str:
        return f"http://{self.listen}"
