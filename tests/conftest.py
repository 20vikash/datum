import pytest
from fastapi.testclient import TestClient

from datum import Settings, create_app
from datum.api.internals import Identity, TokenStore
from datum.api.internals.providers import MetricProvider
from datum.api.internals.schemas import Sample

TOKEN = "a-token-central-minted"
IDENTITY = Identity(tenant="acme", source="pilot_1", labels={"region": "ap_south_1"})
SETTINGS = Settings(url="http://localhost:8428")


class FakeProvider(MetricProvider):
    """Stands in for a real store, so route tests do not depend on how far
    `VictoriaMetricsProvider` has been written."""

    name = "fake"

    def __init__(self, **options):
        self.options = options
        self.written: list[Sample] = []

    def write(self, samples):
        self.written.extend(samples)
        return len(samples)

    def fetch(self, spec):
        return []

    @property
    def metrics(self):
        return ["system_cpu_percent"]

    def get_labels(self, metric):
        return ["region"]

    def get_label_values(self, metric, label):
        return ["ap_south_1"]


@pytest.fixture
def tokens():
    return TokenStore({TOKEN: IDENTITY})


@pytest.fixture
def client(tokens):
    """Authenticated, the way a producer talks to the service."""
    app = create_app(SETTINGS, tokens=tokens)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as test_client:
        app.state.store.provider = FakeProvider()
        yield test_client


@pytest.fixture
def anonymous():
    app = create_app(SETTINGS, tokens=TokenStore())
    with TestClient(app) as test_client:
        yield test_client
