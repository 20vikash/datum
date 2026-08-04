"""Remote write 1.0: snappy-compressed `prometheus.WriteRequest`."""

from __future__ import annotations

import pytest
import snappy

from datum.api.internals import RemoteWriteError
from datum.api.internals import decode as decode_batch
from datum.api.internals.remote_write.remote_pb2 import WriteRequest
from datum.api.internals.remote_write.wire import MAX_DECOMPRESSED_BYTES

CONTENT_TYPE = "application/x-protobuf"
VERSION_2_CONTENT_TYPE = "application/x-protobuf;proto=io.prometheus.write.v2.Request"


def decode(body: bytes, content_type: str = CONTENT_TYPE):
    """The route always sends a content type; these tests mostly do not care which."""
    return decode_batch(body, content_type)


def series(labels: dict[str, str], readings: list[tuple[float, int]]) -> dict:
    return {
        "labels": [{"name": name, "value": value} for name, value in labels.items()],
        "samples": [{"value": value, "timestamp": at} for value, at in readings],
    }


def write_request(*timeseries: dict) -> bytes:
    return snappy.compress(WriteRequest(timeseries=list(timeseries)).SerializeToString())


def varint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


ONE_SERIES = write_request(
    series({"__name__": "system_cpu_percent", "region": "blr"}, [(12.5, 1_754_308_800_000)])
)


class TestDecode:
    def test_metric_name_comes_out_of_the_name_label(self):
        [decoded] = decode(ONE_SERIES)

        assert decoded.metric == "system_cpu_percent"
        assert decoded.labels == {"region": "blr"}
        assert decoded.value == 12.5
        assert decoded.ts.timestamp() == 1_754_308_800.0

    def test_series_labels_apply_to_every_sample_it_carries(self):
        payload = write_request(
            series({"__name__": "queue_depth", "node": "a"}, [(1.0, 1000), (2.0, 2000)])
        )

        decoded = decode(payload)

        assert [each.value for each in decoded] == [1.0, 2.0]
        assert {each.labels["node"] for each in decoded} == {"a"}

    def test_several_series_in_one_batch(self):
        payload = write_request(
            series({"__name__": "one"}, [(1.0, 1000)]),
            series({"__name__": "two"}, [(2.0, 1000)]),
        )

        assert [each.metric for each in decode(payload)] == ["one", "two"]

    def test_fields_we_do_not_store_are_skipped_not_fatal(self):
        """Exemplars, histograms and metadata are absent from our .proto, so
        protobuf keeps them as unknown fields. A real sender emits them."""
        message = WriteRequest(timeseries=[series({"__name__": "requests"}, [(1.0, 1000)])])
        # Field 3 on WriteRequest is `metadata`, absent from our .proto.
        raw = message.SerializeToString() + b"\x1a\x08whatever"

        [decoded] = decode(snappy.compress(raw))

        assert decoded.metric == "requests"

    def test_negative_timestamp_is_accepted(self):
        payload = write_request(series({"__name__": "old"}, [(1.0, -1000)]))

        assert decode(payload)[0].ts.year == 1969


class TestRefusals:
    def test_remote_write_2_is_refused_by_name(self):
        with pytest.raises(RemoteWriteError, match="2.0 is not supported"):
            decode(ONE_SERIES, VERSION_2_CONTENT_TYPE)

    def test_body_that_is_not_snappy(self):
        with pytest.raises(RemoteWriteError, match="not snappy"):
            decode(b'{"samples": []}')

    def test_snappy_that_is_not_a_write_request(self):
        with pytest.raises(RemoteWriteError, match="not a prometheus.WriteRequest"):
            decode(snappy.compress(b"\x0a\x50short"))

    def test_empty_body(self):
        with pytest.raises(RemoteWriteError, match="snappy header"):
            decode(b"")

    def test_series_without_a_name_label(self):
        with pytest.raises(RemoteWriteError, match="__name__"):
            decode(write_request(series({"region": "blr"}, [(1.0, 1000)])))

    def test_empty_batch(self):
        with pytest.raises(RemoteWriteError, match="no samples"):
            decode(snappy.compress(b""))

    def test_illegal_metric_name(self):
        with pytest.raises(RemoteWriteError, match="sanitise"):
            decode(write_request(series({"__name__": "cpu.percent"}, [(1.0, 1000)])))

    def test_reserved_label_from_the_wire(self):
        payload = write_request(series({"__name__": "cpu", "tenant_id": "other"}, [(1.0, 1000)]))

        with pytest.raises(RemoteWriteError, match="token"):
            decode(payload)

    def test_non_finite_value(self):
        payload = write_request(series({"__name__": "cpu"}, [(float("nan"), 1000)]))

        with pytest.raises(RemoteWriteError, match="finite"):
            decode(payload)

    def test_batch_over_the_sample_cap(self):
        crowd = [series({"__name__": "cpu"}, [(1.0, 1000)] * 1000) for _ in range(11)]

        with pytest.raises(RemoteWriteError, match="at most"):
            decode(write_request(*crowd))

    def test_decompression_bomb_is_refused_by_its_header(self):
        """The header claims a gigabyte. It is refused without decompressing."""
        with pytest.raises(RemoteWriteError, match="decompresses to over"):
            decode(varint(1 << 30) + b"\x00")

    def test_the_size_cap_is_read_off_the_header_not_the_body(self):
        assert len(varint(MAX_DECOMPRESSED_BYTES + 1) + b"\x00") < 10


def post(client, body: bytes, content_type: str = "application/x-protobuf"):
    return client.post(
        "/v1/write",
        content=body,
        headers={"content-type": content_type, "content-encoding": "snappy"},
    )


class TestRoute:
    def test_a_batch_lands_stamped_with_the_caller(self, client):
        payload = write_request(
            series({"__name__": "system_cpu_percent"}, [(12.5, 1_754_308_800_000)])
        )

        response = post(client, payload)

        assert response.status_code == 204
        assert response.content == b""
        [written] = client.app.state.store.provider.written
        assert written.metric == "system_cpu_percent"
        assert written.labels == {
            "region": "ap_south_1",
            "tenant_id": "acme",
            "source_id": "pilot_1",
        }

    def test_a_label_the_token_fixes_is_refused_and_nothing_lands(self, client):
        payload = write_request(series({"__name__": "cpu", "region": "blr"}, [(1.0, 1000)]))

        response = post(client, payload)

        assert response.status_code == 400
        assert "token" in response.text
        assert client.app.state.store.provider.written == []

    def test_one_bad_series_rejects_the_whole_batch(self, client):
        payload = write_request(
            *[series({"__name__": "cpu"}, [(1.0, 1000)]) for _ in range(999)],
            series({"__name__": "cpu.percent"}, [(1.0, 1000)]),
        )

        response = post(client, payload)

        assert response.status_code == 400
        assert client.app.state.store.provider.written == []

    def test_a_malformed_body_is_a_400_not_a_500(self, client):
        assert post(client, b"not snappy at all").status_code == 400

    def test_remote_write_2_is_refused(self, client):
        response = post(client, ONE_SERIES, VERSION_2_CONTENT_TYPE)

        assert response.status_code == 400
        assert "2.0 is not supported" in response.text

    def test_a_stranger_is_turned_away(self, anonymous):
        assert post(anonymous, ONE_SERIES).status_code == 401
