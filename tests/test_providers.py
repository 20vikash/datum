from datetime import UTC, datetime

import pytest

from datum.api.internals.providers import (
    MetricProvider,
    ProviderError,
    VictoriaMetricsProvider,
)
from datum_sql import QuerySpec


def test_a_provider_missing_a_method_cannot_be_built():
    class Half(MetricProvider):
        name = "half"

        def fetch(self, spec):
            return []

    with pytest.raises(TypeError, match="abstract"):
        Half()


def test_the_victoria_provider_normalises_its_url():
    assert VictoriaMetricsProvider(url="http://localhost:8428/").url == "http://localhost:8428"


def test_an_unreachable_store_is_a_provider_error():
    provider = VictoriaMetricsProvider(url="http://127.0.0.1:1", timeout=0.5)
    spec = QuerySpec(
        metric="cpu",
        start=datetime(2026, 8, 4, tzinfo=UTC),
        end=datetime(2026, 8, 4, 1, tzinfo=UTC),
        step="15s",
    )

    with pytest.raises(ProviderError, match="unreachable"):
        provider.fetch(spec)


def test_matrix_rows_are_flattened_with_labels():
    data = {
        "result": [
            {
                "metric": {"__name__": "cpu", "host": "a"},
                "values": [[1785836545, "1280"], [1785836605, "1290"]],
            }
        ]
    }

    rows = VictoriaMetricsProvider._rows(data)

    assert len(rows) == 2
    assert rows[0]["host"] == "a"
    assert rows[0]["value"] == 1280.0
    assert rows[0]["ts"] == datetime(2026, 8, 4, 9, 42, 25, tzinfo=UTC)
    assert "__name__" not in rows[0]


def test_stale_markers_are_dropped_not_stored():
    data = {"result": [{"metric": {"__name__": "cpu"}, "values": [[1, "NaN"], [2, "1.5"]]}]}

    rows = VictoriaMetricsProvider._rows(data)

    assert [row["value"] for row in rows] == [1.5]


def test_an_empty_result_is_no_rows():
    assert VictoriaMetricsProvider._rows({"result": []}) == []
