from __future__ import annotations

import urllib.error
import urllib.request
from typing import ClassVar

from datum.api.internals.providers.base import MetricProvider, ProviderError
from datum.api.internals.schemas import Sample
from datum_sql import QuerySpec

IMPORT_PATH = "/api/v1/import/prometheus"
QUERY_PATH = "/api/v1/query"
SERIES_PATH = "/api/v1/series"


class VictoriaMetricsProvider(MetricProvider):
    """The production provider. HTTP against a Prometheus-compatible API.

    No credential: VictoriaMetrics runs on the same machine and must listen on
    loopback, since it has no auth of its own. FastAPI is the only way in.
    """

    name: ClassVar[str] = "victoriametrics"

    def __init__(self, url: str, timeout: float = 10.0, **options):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.options = options

    def write(self, samples: list[Sample]) -> int:
        """Import in Prometheus exposition format, one sample per line."""
        if not samples:
            return 0

        body = "\n".join(self.render(sample) for sample in samples)
        self._post(IMPORT_PATH, body.encode())
        return len(samples)

    @staticmethod
    def render(sample: Sample) -> str:
        """`metric{label="value"} 12.5 1754308800000`, milliseconds since epoch."""
        pairs = ",".join(
            f'{name}="{escape(value)}"' for name, value in sorted(sample.labels.items())
        )
        series = f"{sample.metric}{{{pairs}}}" if pairs else sample.metric
        return f"{series} {sample.value} {int(sample.ts.timestamp() * 1000)}"

    def fetch(self, spec: QuerySpec) -> list[dict]:
        raise NotImplementedError(f"GET {self.url}{QUERY_PATH} with {spec.selector!r}")

    @property
    def metrics(self) -> list[str]:
        raise NotImplementedError(f"GET {self.url}/api/v1/label/__name__/values")

    def get_labels(self, metric: str) -> list[str]:
        raise NotImplementedError(f"GET {self.url}{SERIES_PATH} for {metric!r}")

    def get_label_values(self, metric: str, label: str) -> list[str]:
        raise NotImplementedError(f"GET {self.url}/api/v1/label/{label}/values")

    def _post(self, path: str, body: bytes) -> None:
        """Anything other than a clean 2xx is a `ProviderError`, never a silent drop."""
        request = urllib.request.Request(f"{self.url}{path}", data=body, method="POST")
        request.add_header("Content-Type", "text/plain; charset=utf-8")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout):
                return
        except urllib.error.HTTPError as refused:
            raise ProviderError(f"{path} returned {refused.code}: {refused.reason}") from refused
        except (urllib.error.URLError, TimeoutError) as unreachable:
            raise ProviderError(f"{self.url} is unreachable: {unreachable}") from unreachable


def escape(value: str) -> str:
    """Backslash, quote and newline, per the exposition format."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
