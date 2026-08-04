from __future__ import annotations

import re

NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
LABEL = re.compile(r"^[a-z_][a-z0-9_]*$")

class BadName(ValueError):
    """A metric or label name that would be wrong to store."""


def build(namespace: str, subsystem: str, target: str, unit: str = "", suffix: str = "") -> str:
    """`namespace_subsystem_target_unit_suffix`, with the empty parts dropped.

        build("pilot", "process", "memory_rss", "bytes")   -> pilot_process_memory_rss_bytes
        build("pilot", "process", "io_read", "bytes", "total")

    The unit is appended, not checked, as `prometheus_client` does it: base
    units are a convention the caller keeps, not something enforced here.
    """
    if unit and (target == unit or target.endswith(f"_{unit}")):
        unit = ""  # already spelled out, as prometheus_client does
    parts = [part for part in (namespace, subsystem, target, unit, suffix) if part]
    return validate("_".join(parts))


def validate(name: str) -> str:
    """Reject anything VictoriaMetrics would take but nobody could query sanely."""
    if not NAME.match(name):
        raise BadName(f"{name!r} must be lowercase, and '.' or '-' must become '_'")
    if len(name) > 200:
        raise BadName(f"{name!r} is too long")
    return name


CHURNING = frozenset({"pid", "container_id", "request_id", "trace_id", "uuid"})


def validate_labels(labels: dict[str, str], churning_allowed: bool = False) -> dict[str, str]:
    """Label names follow the same rule, and the unbounded ones are refused.

    `churning_allowed` is for `_info` metrics, which exist to carry exactly
    these and confine the churn to one series instead of all of them.
    """
    for key in labels:
        if key in CHURNING and not churning_allowed:
            raise BadName(
                f"{key!r} changes constantly, so it would make a new series each time. "
                "Label by service instead, and put it on an _info metric."
            )
        if not LABEL.match(key):
            raise BadName(f"label {key!r} must be lowercase with underscores")
    return {key: str(value) for key, value in labels.items()}


