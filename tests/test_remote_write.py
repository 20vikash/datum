from datetime import UTC, datetime

import cramjam
import pytest

from datum.api.internals.remote import RemoteWriteError, TooManySamples, decode
from datum.api.internals.remote.remote_write_pb2 import WriteRequest
from datum.config import MAX_BATCH

PATH = "/v1/ingest/remote"
V2 = "application/x-protobuf;proto=io.prometheus.write.v2.Request"
RESOURCE = "acme"


def written(*series: tuple[dict, list[tuple[float, int]]]) -> bytes:
    """One remote write body, the way vmagent would send it."""
    request = WriteRequest()
    for labels, samples in series:
        stream = request.timeseries.add()
        for name, value in labels.items():
            stream.labels.add(name=name, value=value)
        for value, timestamp in samples:
            stream.samples.add(value=value, timestamp=timestamp)
    return bytes(cramjam.snappy.compress_raw(request.SerializeToString()))


def test_a_series_becomes_one_row_per_reading():
    body = written(({"__name__": "cpu", "host": "a"}, [(1.5, 1785836545000), (2.5, 1785836605000)]))

    rows = decode(body, RESOURCE)

    assert [row["value"] for row in rows] == [1.5, 2.5]
    assert rows[0]["metric"] == "cpu"
    assert rows[0]["labels"] == {"host": "a"}
    assert rows[0]["resource_id"] == RESOURCE
    assert rows[0]["ts"] == datetime(2026, 8, 4, 9, 42, 25, tzinfo=UTC)


def test_the_name_label_becomes_the_metric_and_leaves_the_labels():
    rows = decode(written(({"__name__": "cpu"}, [(1.0, 1)])), RESOURCE)

    assert rows[0]["metric"] == "cpu"
    assert rows[0]["labels"] == {}


def test_readings_in_one_series_share_its_labels():
    """Checked once per series, not once per reading."""
    rows = decode(written(({"__name__": "cpu", "host": "a"}, [(1.0, 1), (2.0, 2)])), RESOURCE)

    assert rows[0]["labels"] is rows[1]["labels"]


def test_a_series_without_a_name_is_refused():
    with pytest.raises(RemoteWriteError, match="__name__"):
        decode(written(({"host": "a"}, [(1.0, 1)])), RESOURCE)


def test_a_metric_name_that_cannot_be_stored_is_refused():
    with pytest.raises(RemoteWriteError, match="cannot be stored"):
        decode(written(({"__name__": "not a name"}, [(1.0, 1)])), RESOURCE)


def test_a_label_name_that_cannot_be_stored_is_refused():
    with pytest.raises(RemoteWriteError, match="cannot be stored"):
        decode(written(({"__name__": "cpu", "not a label": "x"}, [(1.0, 1)])), RESOURCE)


def test_a_batch_is_capped_the_same_as_json_ingest():
    readings = [(1.0, index) for index in range(MAX_BATCH + 1)]

    with pytest.raises(TooManySamples, match=str(MAX_BATCH)):
        decode(written(({"__name__": "cpu"}, readings)), RESOURCE)


def test_the_cap_counts_across_series_not_within_one():
    half = [(1.0, index) for index in range(MAX_BATCH // 2 + 1)]

    with pytest.raises(TooManySamples):
        decode(written(({"__name__": "cpu"}, half), ({"__name__": "memory"}, half)), RESOURCE)


def test_an_oversized_batch_is_a_413(client):
    body = written(({"__name__": "cpu"}, [(1.0, index) for index in range(MAX_BATCH + 1)]))

    assert client.post(PATH, content=body).status_code == 413


def test_an_uncompressed_body_is_refused():
    with pytest.raises(RemoteWriteError, match="snappy"):
        decode(b"definitely not snappy", RESOURCE)


def test_the_route_stores_what_it_decoded(client, provider):
    body = written(({"__name__": "cpu", "host": "a"}, [(1.5, 1785836545000)]))

    response = client.post(PATH, content=body)

    assert response.status_code == 204
    assert response.content == b""
    assert provider.written[0]["metric"] == "cpu"
    assert provider.written[0]["resource_id"] == "acme"


def test_the_token_still_owns_the_resource_id(client, provider):
    """Remote write carries labels the producer chose. Not this one."""
    client.post(
        PATH, content=written(({"__name__": "cpu", "resource_id": "elsewhere"}, [(1.0, 1)]))
    )

    assert provider.written[0]["resource_id"] == "acme"
    assert "resource_id" not in provider.written[0]["labels"]


def test_a_broken_body_is_a_400_not_a_500(client):
    response = client.post(PATH, content=b"nonsense")

    assert response.status_code == 400


def test_version_two_is_refused_by_name(client):
    body = written(({"__name__": "cpu"}, [(1.0, 1)]))

    response = client.post(PATH, content=body, headers={"Content-Type": V2})

    assert response.status_code == 415
    assert "v1" in response.json()["detail"]


def test_remote_write_needs_a_writer(anonymous):
    assert anonymous.post(PATH, content=b"").status_code == 401
