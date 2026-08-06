"""Prometheus remote write v1: snappy off, protobuf out, rows in."""

from __future__ import annotations

from datetime import UTC, datetime

import cramjam
from google.protobuf.message import DecodeError

from datum.api.internals.remote.remote_write_pb2 import WriteRequest
from datum.api.internals.schemas import NAME
from datum.config.clickhouse import RESOURCE_LABEL
from datum.config.limits import MAX_BATCH, MAX_DECOMPRESSED

NAME_LABEL = "__name__"
# What Prometheus and vmagent send. A v2 request interns its strings in a
# symbols table, so decoding it as v1 would yield labels that are not there.
CONTENT_TYPE = "application/x-protobuf"
V2 = "io.prometheus.write.v2.request"

UNREADABLE = (DecodeError, cramjam.DecompressionError, ValueError, OSError)


class RemoteWriteError(ValueError):
    """The body was not a snappy-compressed v1 WriteRequest."""


class TooManySamples(RemoteWriteError):
    """More samples than one batch holds. Told apart so it answers 413."""


class BodyTooLarge(RemoteWriteError):
    """Decompresses past what a batch could hold. Also a 413."""


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
    """Decompressed outside the `try`: an oversized body is a 413, and catching
    it here would report it as an unreadable one."""
    payload = _decompressed(body)
    request = WriteRequest()
    try:
        request.ParseFromString(payload)
    except UNREADABLE as unreadable:
        raise RemoteWriteError(f"body is not a v1 WriteRequest: {unreadable}") from unreadable
    return request


def _decompressed(body: bytes) -> bytes:
    """Sized from the snappy header before a buffer exists, so a body that is
    small on the wire cannot become a large one in memory."""
    declared = _declared_length(body)
    if declared > MAX_DECOMPRESSED:
        raise BodyTooLarge(f"{declared} bytes decompressed, but the cap is {MAX_DECOMPRESSED}")

    buffer = bytearray(declared)
    try:
        written = cramjam.snappy.decompress_raw_into(body, buffer)
    except UNREADABLE as unreadable:
        raise RemoteWriteError(f"body is not snappy: {unreadable}") from unreadable
    return bytes(memoryview(buffer)[:written])


def _declared_length(body: bytes) -> int:
    """What the snappy header says it holds. Read, not trusted: it costs nothing
    to lie here, so the number is checked before it is allocated against."""
    try:
        return cramjam.snappy.decompress_raw_len(body)
    except UNREADABLE as unreadable:
        raise RemoteWriteError(f"body is not snappy: {unreadable}") from unreadable
