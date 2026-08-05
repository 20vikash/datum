from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
MAX_BATCH = 10_000


class QueryRequest(BaseModel):
    sql: str = Field(examples=["SELECT ts, value FROM datum.samples WHERE metric = 'cpu'"])


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict]
    truncated: bool


class MetricList(BaseModel):
    metrics: list[str]


class ColumnList(BaseModel):
    metric: str
    columns: list[str]


class Sample(BaseModel):
    """One reading. `resource_id` is absent by design: the token decides it."""

    metric: str = Field(pattern=NAME.pattern, max_length=200)
    value: float
    ts: datetime
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("labels")
    @classmethod
    def _label_names(cls, labels: dict[str, str]) -> dict[str, str]:
        unusable = sorted(name for name in labels if not NAME.match(name))
        if unusable:
            raise ValueError(f"label names must match {NAME.pattern}: {', '.join(unusable)}")
        return labels


class SamplesRequest(BaseModel):
    samples: list[Sample] = Field(min_length=1, max_length=MAX_BATCH)


class IngestResponse(BaseModel):
    accepted: int
