from __future__ import annotations

import math
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
RESERVED_LABELS = frozenset({"__name__", "tenant_id", "source_id"})

MAX_SAMPLES = 10_000
MAX_LABELS = 30
MAX_LABEL_VALUE = 256


class Sample(BaseModel):
    """One number, at one time, for one set of labels.

    No type field: VictoriaMetrics stores no metric type, so the name suffix
    carries the intent. No tenant or source either; those come from the token.
    """

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(max_length=200, examples=["system_cpu_percent"])
    labels: dict[str, str] = Field(default_factory=dict, examples=[{"region": "ap-south-1"}])
    value: float
    ts: datetime = Field(
        description="RFC 3339. Required: the producer observed it, so the producer times it."
    )

    @field_validator("metric")
    @classmethod
    def _metric_is_prometheus_legal(cls, name: str) -> str:
        if not METRIC_NAME.match(name):
            raise ValueError(f"{name!r} is not a legal metric name; sanitise '.' to '_'")
        return name

    @field_validator("value")
    @classmethod
    def _value_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("value must be finite; NaN and Inf are not accepted")
        return value

    @field_validator("labels")
    @classmethod
    def _labels_are_legal(cls, labels: dict[str, str]) -> dict[str, str]:
        if len(labels) > MAX_LABELS:
            raise ValueError(f"at most {MAX_LABELS} labels per sample")
        for name, value in labels.items():
            if name in RESERVED_LABELS:
                raise ValueError(f"{name!r} comes from the token, not the body")
            if not LABEL_NAME.match(name):
                raise ValueError(f"{name!r} is not a legal label name")
            if len(value) > MAX_LABEL_VALUE:
                raise ValueError(f"label {name!r} exceeds {MAX_LABEL_VALUE} characters")
        return labels


class IngestRequest(BaseModel):
    """One batch. Fire and forget: the producer ignores the response."""

    model_config = ConfigDict(extra="forbid")

    samples: list[Sample] = Field(min_length=1, max_length=MAX_SAMPLES)


class IngestAccepted(BaseModel):
    accepted: int


class QueryRequest(BaseModel):
    sql: str = Field(examples=["SELECT * FROM system_cpu_percent WHERE region = 'ap-south-1'"])
    dialect: str = "mysql"
    mode: str = Field(default="raw", pattern="^(raw|step)$")


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict]
    truncated: bool


class ExplainResponse(BaseModel):
    """What `plan()` decided, without fetching anything."""

    promql: str
    start: datetime
    end: datetime
    step: str
    mode: str
    columns: list[str] | None
    limit: int | None


class MetricList(BaseModel):
    metrics: list[str]


class ColumnList(BaseModel):
    metric: str
    columns: list[str]
