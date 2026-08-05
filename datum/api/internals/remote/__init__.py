"""Prometheus remote write v1: snappy off, protobuf out, rows in."""

from __future__ import annotations

from datetime import UTC, datetime

import cramjam
from google.protobuf.message import DecodeError

from datum.api.internals.remote.remote_write_pb2 import WriteRequest
from datum.api.internals.schemas import MAX_BATCH, NAME
from datum.config.clickhouse import RESOURCE_LABEL

NAME_LABEL = "__name__"
# What Prometheus and vmagent send. A v2 request interns its strings in a
# symbols table, so decoding it as v1 would yield labels that are not there.
CONTENT_TYPE = "application/x-protobuf"
V2 = "io.prometheus.write.v2.request"


class RemoteWriteError(ValueError):
    """The body was not a snappy-compressed v1 WriteRequest."""


class TooManySamples(RemoteWriteError):
    """More samples than one batch holds. Told apart so it answers 413."""


def is_version_two(content_type: str) -> bool:
    return V2 in content_type.lower()


def decode(body: bytes, resource_id: str) -> list[dict]:
    """Table rows for one request, flattened out of their series.

    Rows are built directly rather than through `Sample`: a name and its labels
    belong to the series, so they are checked once each however many readings
    hang off them. Counted first, so an oversized request costs only the parse.
    """
    request = _parse(body)
    total = sum(len(series.samples) for series in request.timeseries)
    if total > MAX_BATCH:
        raise TooManySamples(f"{total} samples, but a batch holds {MAX_BATCH}")

    rows = []
    for series in request.timeseries:
        metric, labels = _series(series)
        rows.extend(
            {
                "ts": datetime.fromtimestamp(sample.timestamp / 1000, UTC),
                "metric": metric,
                RESOURCE_LABEL: resource_id,
                "labels": labels,
                "value": sample.value,
            }
            for sample in series.samples
        )
    return rows


def _series(series) -> tuple[str, dict[str, str]]:
    """The metric and labels every reading in one series shares.

    `resource_id` is dropped here the same way it is on the JSON path: the
    token decides it, and a producer cannot claim another machine's.
    """
    metric = ""
    labels = {}
    for label in series.labels:
        if label.name == NAME_LABEL:
            metric = label.value
        elif label.name != RESOURCE_LABEL:
            labels[label.name] = label.value

    if not metric:
        raise RemoteWriteError("a series carries no __name__ label")
    for name in (metric, *labels):
        if not NAME.match(name):
            raise RemoteWriteError(f"{name!r} cannot be stored: it must match {NAME.pattern}")
    return metric, labels


def _parse(body: bytes) -> WriteRequest:
    try:
        request = WriteRequest()
        request.ParseFromString(bytes(cramjam.snappy.decompress_raw(body)))
    except (DecodeError, cramjam.DecompressionError, ValueError, OSError) as unreadable:
        raise RemoteWriteError(f"body is not a snappy WriteRequest: {unreadable}") from unreadable
    return request
