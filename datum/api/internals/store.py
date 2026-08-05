from __future__ import annotations

from datum.api.internals.providers import MetricProvider, Rows
from datum.api.internals.schemas import Sample
from datum.config.clickhouse import RESOURCE_LABEL


class MetricStore:
    """The store as the service uses it, backed by one `MetricProvider`."""

    def __init__(self, provider: MetricProvider):
        self.provider = provider

    def ensure_schema(self) -> None:
        self.provider.ensure_schema()

    def query(self, sql: str) -> Rows:
        return self.provider.fetch(sql)

    def ingest(self, samples: list[Sample], resource_id: str) -> int:
        """The token owns `resource_id`. Whatever the body claimed is dropped."""
        return self.provider.ingest([get_row(sample, resource_id) for sample in samples])

    @property
    def metrics(self) -> list[str]:
        return self.provider.metrics

    def get_columns(self, metric: str) -> list[str]:
        """The table as a caller sees it, with the label map flattened out."""
        return ["ts", "metric", RESOURCE_LABEL, *self.provider.get_labels(metric), "value"]


def get_row(sample: Sample, resource_id: str) -> dict:
    labels = {name: value for name, value in sample.labels.items() if name != RESOURCE_LABEL}
    return {
        "ts": sample.ts,
        "metric": sample.metric,
        "resource_id": resource_id,
        "labels": labels,
        "value": sample.value,
    }
