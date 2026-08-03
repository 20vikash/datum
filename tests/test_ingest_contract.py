import pytest

from datum.api.internals.schemas import MAX_LABELS, MAX_SAMPLES


def post(client, **overrides):
    sample = {"metric": "system_cpu_percent", "value": 1.0, "ts": "2026-08-04T12:00:00Z"}
    return client.post("/v1/ingest", json={"samples": [sample | overrides]})


def test_a_well_formed_batch_reaches_the_provider(client):
    assert post(client).status_code == 202


def test_dotted_metric_names_are_refused(client):
    response = post(client, metric="system.cpu_percent")

    assert response.status_code == 422
    assert "sanitise" in response.text


@pytest.mark.parametrize("label", ["tenant_id", "source_id", "__name__"])
def test_token_owned_labels_cannot_come_from_the_body(client, label):
    response = post(client, labels={label: "someone_else"})

    assert response.status_code == 422
    assert "token" in response.text


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_values_are_refused(client, value):
    response = client.post(
        "/v1/ingest",
        content=(
            f'{{"samples": [{{"metric": "cpu", "value": {value}, "ts": "2026-08-04T12:00:00Z"}}]}}'
        ),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422


def test_unknown_fields_are_refused_rather_than_ignored(client):
    assert post(client, type="counter").status_code == 422


def test_an_empty_batch_is_refused(client):
    assert client.post("/v1/ingest", json={"samples": []}).status_code == 422


def test_an_oversized_batch_is_refused(client):
    sample = {"metric": "cpu", "value": 1.0, "ts": "2026-08-04T12:00:00Z"}
    samples = [sample] * (MAX_SAMPLES + 1)

    assert client.post("/v1/ingest", json={"samples": samples}).status_code == 422


def test_too_many_labels_are_refused(client):
    labels = {f"label_{index}": "x" for index in range(MAX_LABELS + 1)}

    assert post(client, labels=labels).status_code == 422


def test_illegal_label_names_are_refused(client):
    assert post(client, labels={"has-a-dash": "x"}).status_code == 422


def test_a_missing_timestamp_is_refused(client):
    response = client.post("/v1/ingest", json={"samples": [{"metric": "cpu", "value": 1.0}]})

    assert response.status_code == 422
