from __future__ import annotations

from fastapi import APIRouter

from datum.api.dependencies import Store
from datum.api.internals.schemas import (
    ColumnList,
    ExplainResponse,
    MetricList,
    QueryRequest,
    QueryResponse,
)

router = APIRouter(tags=["query"])


@router.post("/query")
def query(body: QueryRequest, store: Store) -> QueryResponse:
    """Translate the SQL, fetch the rows, shape them."""
    result = store.run(body.sql, body.dialect, body.mode)
    return QueryResponse(columns=result.columns, rows=result.rows, truncated=result.truncated)


@router.post("/query/explain")
def explain(body: QueryRequest, store: Store) -> ExplainResponse:
    """What the SQL translates to, without touching the store."""
    return ExplainResponse(**store.get_plan(body.sql, body.dialect, body.mode).describe())


@router.get("/metrics")
def metrics(store: Store) -> MetricList:
    """Every metric name the store knows about."""
    return MetricList(metrics=store.metrics)


@router.get("/metrics/{metric}/columns")
def columns(metric: str, store: Store) -> ColumnList:
    """Label names for one metric, plus `ts` and `value`."""
    return ColumnList(metric=metric, columns=store.get_columns(metric))
