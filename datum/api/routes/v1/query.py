from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from datum.api.dependencies import Store
from datum.api.internals import ProviderError
from datum.api.internals.schemas import (
    ColumnList,
    ExplainResponse,
    MetricList,
    QueryRequest,
    QueryResponse,
)
from datum_sql import UnsupportedSQL

router = APIRouter(tags=["query"])


@router.post("/query")
def query(body: QueryRequest, store: Store) -> QueryResponse:
    """Translate the SQL, fetch the rows, shape them."""
    result = call_store(lambda: store.run(body.sql, body.dialect, body.mode))
    return QueryResponse(columns=result.columns, rows=result.rows, truncated=result.truncated)


@router.post("/query/explain")
def explain(body: QueryRequest, store: Store) -> ExplainResponse:
    """What the SQL translates to, without touching the store."""
    spec = translate(lambda: store.get_plan(body.sql, body.dialect, body.mode))
    return ExplainResponse(**spec.describe())


@router.get("/metrics")
def metrics(store: Store) -> MetricList:
    """Every metric name the store knows about."""
    return MetricList(metrics=call_store(lambda: store.metrics))


@router.get("/metrics/{metric}/columns")
def columns(metric: str, store: Store) -> ColumnList:
    """Label names for one metric, plus `ts` and `value`."""
    return ColumnList(metric=metric, columns=call_store(lambda: store.get_columns(metric)))


def translate(work):
    """A refused translation is a 400, never a 500."""
    try:
        return work()
    except UnsupportedSQL as refusal:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(refusal)) from refusal


def call_store(work):
    """An unwritten provider is 501; an unreachable one is 503."""
    try:
        return translate(work)
    except NotImplementedError as unwritten:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(unwritten)) from unwritten
    except ProviderError as failure:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(failure)) from failure
