from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    offset: int = 0


class MetricList(BaseModel):
    metrics: list[str]


class ColumnList(BaseModel):
    metric: str
    columns: list[str]
