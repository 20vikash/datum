from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """The store could not be reached. Never swallowed into a silent success."""


class QueryRefused(ProviderError):
    """The store rejected the write. The caller's fault, not the store's."""


class MetricProvider(ABC):
    """What the service needs from a storage engine, and nothing more.

    Subclass it, then point `app.py` at it. One that forgets a method fails at
    construction. Datum writes only: reads go to ClickHouse directly.
    """

    @abstractmethod
    def ensure_schema(self) -> None:
        """Make the store ready to accept samples. Idempotent."""

    @abstractmethod
    def ingest(self, rows: list[dict]) -> int:
        """Write one batch, keyed by column name. Returns rows accepted."""
