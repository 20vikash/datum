from datetime import UTC, datetime

import pytest

from datum.api.internals import Identity, MetricStore, get_provider
from datum.api.internals.providers import (
    PROVIDERS,
    MetricProvider,
    ProviderError,
    VictoriaMetricsProvider,
)
from datum.api.internals.schemas import Sample
from tests.conftest import FakeProvider


def test_only_victoriametrics_ships():
    assert list(PROVIDERS) == ["victoriametrics"]


def test_a_provider_is_built_by_name():
    assert isinstance(get_provider("victoriametrics", url="http://x"), VictoriaMetricsProvider)


def test_options_reach_the_provider():
    provider = get_provider("victoriametrics", url="http://x", timeout=2.0)

    assert provider.timeout == 2.0


def test_an_unknown_provider_names_the_ones_that_exist():
    with pytest.raises(LookupError, match="victoriametrics"):
        get_provider("clickhouse")


def test_a_registered_provider_is_reachable_by_name(monkeypatch):
    monkeypatch.setitem(PROVIDERS, FakeProvider.name, FakeProvider)

    assert isinstance(get_provider("fake"), FakeProvider)


def test_a_provider_missing_a_method_cannot_be_built():
    class Half(MetricProvider):
        name = "half"

        def write(self, samples):
            return len(samples)

    with pytest.raises(TypeError, match="abstract"):
        Half()


def test_the_victoria_provider_normalises_its_url():
    assert VictoriaMetricsProvider(url="http://localhost:8428/").url == "http://localhost:8428"


def test_ingest_stamps_a_receipt_time():
    provider = FakeProvider()
    identity = Identity(tenant="acme", source="pilot_1")

    accepted = MetricStore(provider).ingest([Sample(metric="cpu", value=1.0, ts=datetime(2026, 8, 4, tzinfo=UTC))], identity)

    assert accepted == 1
    assert provider.written[0].ts is not None


def test_exposition_line_carries_labels_and_millisecond_time():
    sample = Sample(
        metric="system_cpu_percent",
        value=12.5,
        ts=datetime(2026, 8, 4, tzinfo=UTC),
        labels={"region": "ap_south_1", "host": "a"},
    )

    line = VictoriaMetricsProvider.render(sample)

    assert line == 'system_cpu_percent{host="a",region="ap_south_1"} 12.5 1785801600000'


def test_a_sample_without_labels_has_no_braces():
    sample = Sample(metric="cpu", value=1.0, ts=datetime(2026, 8, 4, tzinfo=UTC))

    assert VictoriaMetricsProvider.render(sample) == "cpu 1.0 1785801600000"


def test_label_values_are_escaped():
    sample = Sample(
        metric="cpu", value=1.0, ts=datetime(2026, 8, 4, tzinfo=UTC), labels={"path": 'a"b\\c'}
    )

    assert 'path="a\\"b\\\\c"' in VictoriaMetricsProvider.render(sample)


def test_an_unreachable_store_is_a_provider_error():
    provider = VictoriaMetricsProvider(url="http://127.0.0.1:1", timeout=0.5)
    sample = Sample(metric="cpu", value=1.0, ts=datetime(2026, 8, 4, tzinfo=UTC))

    with pytest.raises(ProviderError, match="unreachable"):
        provider.write([sample])


def test_an_empty_batch_never_reaches_the_network():
    assert VictoriaMetricsProvider(url="http://127.0.0.1:1").write([]) == 0
