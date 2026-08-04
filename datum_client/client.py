from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import UTC, datetime

from datum_client.naming import build, validate_labels

logger = logging.getLogger("datum")

TIMEOUT = 2.0
MAX_SAMPLES = 10_000


class Batch:
    """Samples for one namespace, named the same way every time.

    `namespace` and `subsystem` are fixed here so call sites pass only what
    varies, which is what keeps names consistent across producers.
    """

    def __init__(self, namespace: str, subsystem: str = "", **labels):
        self.namespace = namespace
        self.subsystem = subsystem
        self.labels = validate_labels(labels)
        self.samples: list[dict] = []

    def gauge(self, target: str, value: float, unit: str = "", ts=None, **labels) -> Batch:
        """A value that goes up and down: a percentage, a size, a queue depth."""
        return self._add(build(self.namespace, self.subsystem, target, unit), value, ts, labels)

    def counter(self, target: str, value: float, unit: str = "", ts=None, **labels) -> Batch:
        """A value that only climbs. Gets `_total`, so PromQL can rate() it."""
        name = build(self.namespace, self.subsystem, target, unit, "total")
        return self._add(name, value, ts, labels)

    def up(self, target: str, is_up: bool, ts=None, **labels) -> Batch:
        """The `up` convention: absence is invisible, 0 is alertable."""
        return self._add(build(self.namespace, self.subsystem, target, "", "up"), int(is_up), ts, labels)

    def info(self, target: str, ts=None, **labels) -> Batch:
        """Always 1, carrying facts as labels. The one place a pid belongs."""
        name = build(self.namespace, self.subsystem, target, "", "info")
        return self._add(name, 1, ts, labels, churning_allowed=True)

    def _add(self, name: str, value: float, ts, labels: dict, churning_allowed=False) -> Batch:
        if len(self.samples) >= MAX_SAMPLES:
            raise ValueError(f"a batch holds at most {MAX_SAMPLES} samples")
        moment = ts or datetime.now(UTC)
        self.samples.append(
            {
                "metric": name,
                "value": float(value),
                "ts": moment.isoformat().replace("+00:00", "Z"),
                "labels": {**self.labels, **validate_labels(labels, churning_allowed)},
            }
        )
        return self

    def __len__(self) -> int:
        return len(self.samples)


class Datum:
    """Fire and forget: one POST, a short timeout, no spool and no retry.

    A dropped metric is a gap in a chart. Blocking a producer's collection tick
    to retry one is worse, so `send` never raises on a network failure.
    """

    def __init__(self, url: str, token: str, timeout: float = TIMEOUT):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def send(self, *batches: Batch) -> int:
        """Post one or more batches as a single request.

        Several batches because one tick usually spans several subsystems, and
        they stay separate objects so nothing can write into another's samples.
        Returns the HTTP status, or 0 when the send never landed.
        """
        samples = [sample for batch in batches for sample in batch.samples]
        if not samples:
            return 0
        if len(samples) > MAX_SAMPLES:
            raise ValueError(f"{len(samples)} samples, but a request holds {MAX_SAMPLES}")

        request = urllib.request.Request(
            f"{self.url}/v1/ingest",
            data=json.dumps({"samples": samples}).encode(),
            method="POST",
        )
        request.add_header("Content-Type", "application/json")
        request.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status
        except urllib.error.HTTPError as refused:
            # A 401 or 422 is our bug, not a blip. Silence here means metrics
            # stop and nobody notices, so it is logged even though we go on.
            logger.warning("datum refused %d: %s", refused.code, refused.read()[:500])
            return refused.code
        except (urllib.error.URLError, TimeoutError) as unreachable:
            logger.debug("datum unreachable: %s", unreachable)
            return 0
