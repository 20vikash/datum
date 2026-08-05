import pytest
from fastapi.testclient import TestClient

from datum import create_app
from tests.conftest import SETTINGS, FakeProvider, mint

SAMPLE = {"metric": "system_cpu_percent", "value": 12.5, "ts": "2026-08-05T10:00:00Z"}


def post(client, *samples):
    return client.post("/v1/ingest", json={"samples": list(samples)})


def test_a_batch_is_accepted(client, provider):
    response = post(client, SAMPLE)

    assert response.status_code == 200
    assert response.json() == {"accepted": 1}
    assert len(provider.written) == 1


def test_the_token_decides_the_resource_id(client, provider):
    post(client, {**SAMPLE, "labels": {"region": "ap_south_1"}})

    written = provider.written[0]
    assert written["resource_id"] == "acme"
    assert written["labels"] == {"region": "ap_south_1"}
    assert written["metric"] == "system_cpu_percent"
    assert written["value"] == 12.5


def test_a_claimed_resource_id_in_the_body_is_dropped(client, provider):
    """The token is the only thing that can say who a row belongs to."""
    post(client, {**SAMPLE, "labels": {"resource_id": "someone_else"}})

    written = provider.written[0]
    assert written["resource_id"] == "acme"
    assert "resource_id" not in written["labels"]


def test_a_token_without_a_resource_id_cannot_write(tokens):
    token = mint({"vm_access": {"metrics_extra_labels": ["source_id=pilot_1"]}})
    app = create_app(SETTINGS, tokens=tokens, provider=FakeProvider())

    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        response = post(client, SAMPLE)

    assert response.status_code == 403
    assert "resource_id" in response.json()["detail"]


def test_ingest_is_behind_the_same_gate(anonymous):
    assert post(anonymous, SAMPLE).status_code == 401


def test_an_empty_batch_is_refused(client):
    assert client.post("/v1/ingest", json={"samples": []}).status_code == 422


@pytest.mark.parametrize(
    "sample",
    [
        {**SAMPLE, "metric": "not a name"},
        {**SAMPLE, "labels": {"not a label": "x"}},
        {**SAMPLE, "value": "twelve"},
        {"metric": "cpu", "value": 1.0},
    ],
)
def test_an_unusable_sample_is_a_422(client, sample):
    assert post(client, sample).status_code == 422
