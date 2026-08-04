from __future__ import annotations

from datetime import UTC, datetime

import snappy
from google.protobuf.message import DecodeError
from pydantic import ValidationError

from datum.api.internals.remote_write.remote_pb2 import Sample as WireSample
from datum.api.internals.remote_write.remote_pb2 import TimeSeries, WriteRequest
from datum.api.internals.schemas import MAX_SAMPLES, Sample

METRIC_NAME_LABEL = "__name__"
MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_VARINT_BYTES = 5

VERSION_2_MARKER = "io.prometheus.write.v2.request"


class RemoteWriteError(ValueError):
    """A remote write payload we will not accept. Always the sender's to fix."""


def decode(body: bytes, content_type: str) -> list[Sample]:
    """A snappy-compressed `prometheus.WriteRequest` as samples we can store.

    Every failure is the sender's, so every failure raises `RemoteWriteError`
    and none of the batch is written.
    """
    _reject_version_2(content_type)
    request = WriteRequest()
    try:
        request.ParseFromString(_decompress(body))
    except DecodeError as unreadable:
        raise RemoteWriteError(
            f"the batch is not a prometheus.WriteRequest: {unreadable}"
        ) from unreadable

    samples = [sample for series in request.timeseries for sample in _read_series(series)]
    if not samples:
        raise RemoteWriteError("the batch carries no samples")
    if len(samples) > MAX_SAMPLES:
        raise RemoteWriteError(f"a batch carries at most {MAX_SAMPLES} samples")
    return samples


def _reject_version_2(content_type: str) -> None:
    """Refuse 2.0 by name. Its labels are symbol table references, so parsing
    one as 1.0 yields plausible nonsense rather than an error."""
    if VERSION_2_MARKER in content_type.lower():
        raise RemoteWriteError(
            "remote write 2.0 is not supported; send 1.0 (prometheus.WriteRequest)"
        )


def _decompress(body: bytes) -> bytes:
    """Snappy block format, which is what remote write 1.0 compresses with.

    The declared size is read off the header first, so an overstated one costs
    a varint rather than the allocation it asked for.
    """
    if _declared_size(body) > MAX_DECOMPRESSED_BYTES:
        raise RemoteWriteError(f"the batch decompresses to over {MAX_DECOMPRESSED_BYTES} bytes")
    try:
        return snappy.uncompress(body)
    except snappy.UncompressError as unreadable:
        raise RemoteWriteError(f"the body is not snappy compressed: {unreadable}") from unreadable


def _declared_size(body: bytes) -> int:
    """The uncompressed length a snappy block opens with."""
    size = 0
    for index in range(MAX_VARINT_BYTES):
        if index >= len(body):
            raise RemoteWriteError("the body ended inside its snappy header")
        size |= (body[index] & 0x7F) << (index * 7)
        if not body[index] & 0x80:
            return size
    raise RemoteWriteError("the snappy header is not a valid length")


def _read_series(series: TimeSeries) -> list[Sample]:
    """One TimeSeries: its labels apply to every sample it carries.

    Remote write has no metric field. The name arrives as `__name__`, which is
    reserved on the way in, so it has to come out of the labels here.
    """
    labels = {label.name: label.value for label in series.labels}
    metric = labels.pop(METRIC_NAME_LABEL, None)
    if metric is None:
        raise RemoteWriteError(f"a series arrived without {METRIC_NAME_LABEL}")
    return [_build(metric, labels, sample) for sample in series.samples]


def _build(metric: str, labels: dict[str, str], sample: WireSample) -> Sample:
    """The same validation JSON producers get, reported the same way."""
    try:
        return Sample(
            metric=metric,
            labels=labels,
            value=sample.value,
            ts=datetime.fromtimestamp(sample.timestamp / 1000, UTC),
        )
    except ValidationError as rejected:
        raise RemoteWriteError(f"{metric!r}: {rejected.errors()[0]['msg']}") from rejected
    except (OverflowError, OSError, ValueError) as untimely:
        raise RemoteWriteError(
            f"{metric!r} carries an out of range timestamp: {untimely}"
        ) from untimely
