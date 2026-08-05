from __future__ import annotations

from fastapi import APIRouter

from datum.api.dependencies import Provider, Reader
from datum.api.internals.schemas import ColumnList, MetricList, QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post("/query")
def query(body: QueryRequest, provider: Provider, _: Reader) -> QueryResponse:
    """Run one read against ClickHouse and hand back what it answered."""
    result = provider.fetch(body.sql)
    return QueryResponse(columns=result.columns, rows=result.rows, truncated=result.truncated)


@router.get("/metrics")
def metrics(provider: Provider, _: Reader) -> MetricList:
    return MetricList(metrics=provider.metrics)


@router.get("/metrics/{metric}/columns")
def columns(metric: str, provider: Provider, _: Reader) -> ColumnList:
    return ColumnList(metric=metric, columns=provider.get_columns(metric))
