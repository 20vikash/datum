from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from datum.api.dependencies import Caller, Store
from datum.api.internals import decode

router = APIRouter(tags=["ingest"])


@router.post("/write", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def write(request: Request, store: Store, caller: Caller) -> Response:
    """Decode a snappy-compressed `prometheus.WriteRequest`, then take the ingest path."""
    samples = decode(await request.body(), request.headers.get("content-type", ""))
    store.ingest(samples, caller)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
