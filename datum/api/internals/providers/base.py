from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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
    def fetch(self, sql: str) -> Rows:
        """Rows for one read, as the store answered it."""

    @abstractmethod
    def ingest(self, rows: list[dict]) -> int:
        """Write one batch, keyed by column name. Returns rows accepted."""

    @property
    @abstractmethod
    def metrics(self) -> list[str]:
        """Every metric name the store knows about."""

    @abstractmethod
    def get_labels(self, metric: str) -> list[str]:
        """Label names carried by one metric."""

    @abstractmethod
    def get_label_values(self, metric: str, label: str) -> list[str]:
        """Distinct values of one label on one metric."""
