from __future__ import annotations

from abc import ABC, abstractmethod

from datum_sql import QuerySpec


class ProviderError(RuntimeError):
    """The store refused or could not be reached. Never swallowed into empty rows."""


class MetricProvider(ABC):
    """What the service needs from a storage engine, and nothing more.

    Subclass it to declare a provider, then point `app.py` at it. One that
    forgets a method fails at construction.

    Retrieval only: producers write through vmauth, straight to the store.
    """

    @abstractmethod
    def fetch(self, spec: QuerySpec) -> list[dict]:
        """Rows for one translated query, before projection and ordering."""

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
