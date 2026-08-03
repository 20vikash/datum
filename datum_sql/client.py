"""HTTP client for the Prometheus-compatible API that VictoriaMetrics exposes."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from .spec import QuerySpec

# A metric name in SQL is written with underscores; Prometheus naming forbids
# dots, so producers sanitise them. Keep the mapping visible both ways.
NAME_SEPARATOR = "_"


class QueryError(Exception):
    pass


class VictoriaClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _get(self, path: str, params: list[tuple[str, str]] | None = None) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url)
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read())
        if payload.get("status") != "success":
            raise QueryError(str(payload)[:400])
        return payload["data"]

    # ---------- catalog ----------

    def metrics(self) -> list[str]:
        """Every metric name. These are the tables."""
        return sorted(self._get("/api/v1/label/__name__/values"))

    def labels(self, metric: str) -> list[str]:
        """Label names for one metric. These are the columns."""
        names = self._get("/api/v1/labels", [("match[]", metric)])
        return sorted(name for name in names if name != "__name__")

    def label_values(self, metric: str, label: str) -> list[str]:
        return sorted(self._get(f"/api/v1/label/{label}/values", [("match[]", metric)]))

    # ---------- data ----------

    def fetch(self, spec: QuerySpec) -> list[dict]:
        """One query, flattened into rows of series x samples."""
        if spec.mode == "raw":
            window = max(1, int((spec.end - spec.start).total_seconds()))
            data = self._get(
                "/api/v1/query",
                [
                    ("query", f"{spec.selector}[{window}s]"),
                    ("time", str(int(spec.end.timestamp()))),
                ],
            )
        else:
            data = self._get(
                "/api/v1/query_range",
                [
                    ("query", spec.selector),
                    ("start", str(int(spec.start.timestamp()))),
                    ("end", str(int(spec.end.timestamp()))),
                    ("step", spec.step),
                ],
            )
        rows: list[dict] = []
        for series in data.get("result", []):
            labels = {k: v for k, v in series.get("metric", {}).items() if k != "__name__"}
            for timestamp, value in series.get("values", []):
                row = dict(labels)
                row["ts"] = datetime.fromtimestamp(float(timestamp), UTC)
                row["value"] = float(value)
                rows.append(row)
        return rows
