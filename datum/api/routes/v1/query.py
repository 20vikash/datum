from __future__ import annotations

from fastapi import APIRouter

from datum.api.dependencies import Store
from datum.api.internals.schemas import ColumnList, MetricList, QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post("/query")
def query(body: QueryRequest, store: Store) -> QueryResponse:
    """Run one read against ClickHouse and hand back what it answered."""
    result = store.query(body.sql)
    return QueryResponse(columns=result.columns, rows=result.rows, truncated=result.truncated)


@router.get("/metrics")
def metrics(store: Store) -> MetricList:
    return MetricList(metrics=store.metrics)


@router.get("/metrics/{metric}/columns")
def columns(metric: str, store: Store) -> ColumnList:
    return ColumnList(metric=metric, columns=store.get_columns(metric))
