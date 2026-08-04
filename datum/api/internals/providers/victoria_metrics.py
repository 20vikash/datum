from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from datum.api.internals.providers.base import MetricProvider, ProviderError
from datum_sql import QuerySpec

QUERY_PATH = "/api/v1/query"
RANGE_PATH = "/api/v1/query_range"
LABELS_PATH = "/api/v1/labels"
NAME_VALUES_PATH = "/api/v1/label/__name__/values"


class VictoriaMetricsProvider(MetricProvider):
    """The production provider. HTTP against a Prometheus-compatible API.

    No credential: VictoriaMetrics runs on the same machine and must listen on
    loopback, since it has no auth of its own. Reads arrive through this
    service; writes arrive through vmauth.
    """

    def __init__(self, url: str, timeout: float = 10.0, **options):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.options = options

    def fetch(self, spec: QuerySpec) -> list[dict]:
        """`raw` reads what is stored; `step` resamples onto the grid."""
        if spec.mode == "step":
            data = self._get(
                RANGE_PATH,
                query=spec.selector,
                start=spec.start.timestamp(),
                end=spec.end.timestamp(),
                step=spec.step,
            )
        else:
            window = max(int((spec.end - spec.start).total_seconds()), 1)
            data = self._get(
                QUERY_PATH, query=f"{spec.selector}[{window}s]", time=spec.end.timestamp()
            )
        return self._rows(data)

    @property
    def metrics(self) -> list[str]:
        return sorted(self._get(NAME_VALUES_PATH))

    def get_labels(self, metric: str) -> list[str]:
        names = self._get(LABELS_PATH, **{"match[]": metric})
        return sorted(name for name in names if name != "__name__")

    def get_label_values(self, metric: str, label: str) -> list[str]:
        path = f"/api/v1/label/{urllib.parse.quote(label)}/values"
        return sorted(self._get(path, **{"match[]": metric}))

    @staticmethod
    def _rows(data: dict) -> list[dict]:
        """Flatten a PromQL matrix into rows.

        Non-finite values are stale markers, not readings. They are dropped:
        they mean "no data here", and they cannot be put in a JSON response.
        """
        rows = []
        for series in data.get("result", []):
            labels = {key: value for key, value in series["metric"].items() if key != "__name__"}
            for seconds, value in series.get("values", []):
                number = float(value)
                if math.isfinite(number):
                    rows.append(
                        {
                            **labels,
                            "ts": datetime.fromtimestamp(float(seconds), UTC),
                            "value": number,
                        }
                    )
        return rows

    def _get(self, path: str, **params):
        """GET, and hand back the `data` VictoriaMetrics wrapped its answer in."""
        url = f"{self.url}{path}?{urllib.parse.urlencode(params)}"
        payload = self._call(urllib.request.Request(url, method="GET"), path)
        if payload.get("status") != "success":
            raise ProviderError(f"{path} failed: {payload.get('error', payload)}")
        return payload.get("data", [])

    def _call(self, request, path: str):
        """Anything other than a clean 2xx is a `ProviderError`, never a silent drop."""
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as refused:
            raise ProviderError(f"{path} returned {refused.code}: {refused.reason}") from refused
        except (urllib.error.URLError, TimeoutError) as unreachable:
            raise ProviderError(f"{self.url} is unreachable: {unreachable}") from unreachable
        except json.JSONDecodeError as unreadable:
            raise ProviderError(f"{path} did not return JSON: {unreadable}") from unreadable
