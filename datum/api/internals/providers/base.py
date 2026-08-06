from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from datum.config.clickhouse import RESOURCE_LABEL


class ProviderError(RuntimeError):
    """The store could not be reached. Never swallowed into empty rows."""


class QueryRefused(ProviderError):
    """The store rejected the query. The caller's fault, not the store's."""


@dataclass
class Rows:
    columns: list[str]
    rows: list[dict] = field(default_factory=list)
    truncated: bool = False


class MetricProvider(ABC):
    """What the service needs from a storage engine, and nothing more.

    Subclass it, then point `app.py` at it. One that forgets a method fails at
    construction.
    """

    @abstractmethod
    def ensure_schema(self) -> None:
        """Make the store ready to accept samples. Idempotent."""

    @abstractmethod
    def fetch(self, sql: str, resource_id: str) -> Rows:
        """Rows for one read, as the store answered it, scoped to one resource_id."""

    @abstractmethod
    def ingest(self, rows: list[dict]) -> int:
        """Write one batch, keyed by column name. Returns rows accepted."""

    @abstractmethod
    def get_metrics(self, resource_id: str) -> list[str]:
        """Metric names one resource_id has written."""

    @abstractmethod
    def get_labels(self, metric: str, resource_id: str) -> list[str]:
        """Label names carried by one metric."""

    @abstractmethod
    def get_label_values(self, metric: str, label: str, resource_id: str) -> list[str]:
        """Distinct values of one label on one metric."""

    def get_columns(self, metric: str, resource_id: str) -> list[str]:
        """The table as a caller sees it, with the label map flattened out."""
        return ["ts", "metric", RESOURCE_LABEL, *self.get_labels(metric, resource_id), "value"]
