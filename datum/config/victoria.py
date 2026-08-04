from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VictoriaSettings:
    """How the store runs.

    `listen` stays on loopback: VictoriaMetrics has no auth of its own, so
    vmauth and the API are the only ways in. Binding it anywhere else hands
    every tenant's data to whoever reaches the port.
    """

    listen: str = "127.0.0.1:8428"
    retention: str = "12"
    memory_percent: str = "40"

    # Cardinality limiter. `-1` counts new series and publishes the counters
    # without dropping anything, because over the limit VictoriaMetrics discards
    # silently: the writer still gets 204 and only
    # vm_hourly_series_limit_rows_dropped_total moves. Watch those counters, then
    # set a real number once the normal rate is known. See datum_client's README
    # for why series churn is the thing to watch.
    hourly_series: str = "-1"
    daily_series: str = "-1"

    @property
    def url(self) -> str:
        return f"http://{self.listen}"
