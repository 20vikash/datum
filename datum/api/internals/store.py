from __future__ import annotations

from datum.api.internals.auth import Identity
from datum.api.internals.providers import MetricProvider
from datum.api.internals.schemas import Sample
from datum_sql import QuerySpec, Result, plan, shape


class MetricStore:
    """The store as the service uses it, backed by one `MetricProvider`.

    Owns the SQL to PromQL step and the identity stamp so routes do not. The
    provider below only stores and retrieves.
    """

    def __init__(
        self,
        provider: MetricProvider,
        dialect: str = "mysql",
        mode: str = "raw",
        ignore_pagination: bool = True,
    ):
        self.provider = provider
        self.dialect = dialect
        self.mode = mode
        self.ignore_pagination = ignore_pagination

    def ingest(self, samples: list[Sample], identity: Identity) -> int:
        """Stamp the caller onto every sample, then hand off. Returns how many landed."""
        return self.provider.write(
            [
                sample.model_copy(update={"labels": identity.stamp(sample.labels)})
                for sample in samples
            ]
        )

    def query(self, sql: str, dialect: str | None = None, mode: str | None = None) -> Result:
        """Translate, fetch, then apply what PromQL cannot express."""
        spec = self.get_plan(sql, dialect, mode)
        return shape(self.provider.fetch(spec), spec)

    def get_plan(self, sql: str, dialect: str | None = None, mode: str | None = None) -> QuerySpec:
        """Translate without fetching. Raises `UnsupportedSQL` on a refusal."""
        return plan(
            sql,
            dialect=dialect or self.dialect,
            mode=mode or self.mode,
            ignore_pagination=self.ignore_pagination,
        )

    @property
    def metrics(self) -> list[str]:
        return self.provider.metrics

    def get_columns(self, metric: str) -> list[str]:
        return [*self.provider.get_labels(metric), "ts", "value"]
