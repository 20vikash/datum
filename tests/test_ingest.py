import pytest
from fastapi.testclient import TestClient

from datum import create_app
from datum.config import MAX_LABELS
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


def as_client(tokens, claims):
    """A client carrying one specific set of claims."""
    app = create_app(SETTINGS, tokens=tokens, provider=FakeProvider())
    headers = {"Authorization": f"Bearer {mint(claims)}"}
    return TestClient(app, headers=headers)


def test_a_reader_cannot_write(tokens):
    with as_client(tokens, {"resource_id": "acme", "access": ["read"]}) as client:
        response = post(client, SAMPLE)

    assert response.status_code == 403
    assert "write" in response.json()["detail"]


def test_a_token_without_a_resource_id_is_not_an_identity(tokens):
    """401, not 403: it is not a caller whose access we then judge."""
    with as_client(tokens, {"access": ["read", "write"]}) as client:
        response = post(client, SAMPLE)

    assert response.status_code == 401


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


def test_both_write_paths_agree_on_how_wide_a_sample_is(client):
    """Remote write caps labels off the wire; JSON has to match or the paths
    disagree about what is storable."""
    wide = {**SAMPLE, "labels": {f"label_{index}": "v" for index in range(MAX_LABELS + 1)}}

    assert post(client, wide).status_code == 422


def test_a_sample_of_exactly_the_label_cap_is_accepted(client):
    fits = {**SAMPLE, "labels": {f"label_{index}": "v" for index in range(MAX_LABELS)}}

    assert post(client, fits).status_code == 200
