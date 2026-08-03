from datum.api.internals.providers.base import MetricProvider, ProviderError
from datum.api.internals.providers.victoria_metrics import VictoriaMetricsProvider

PROVIDERS: dict[str, type[MetricProvider]] = {
    VictoriaMetricsProvider.name: VictoriaMetricsProvider,
}


def get_provider(name: str, **options) -> MetricProvider:
    """Build the provider `DATUM_BACKEND` names. Adding one is a line above."""
    if name not in PROVIDERS:
        raise LookupError(f"no storage provider named {name!r}; known: {', '.join(PROVIDERS)}")
    return PROVIDERS[name](**options)


__all__ = ["PROVIDERS", "MetricProvider", "ProviderError", "VictoriaMetricsProvider", "get_provider"]
