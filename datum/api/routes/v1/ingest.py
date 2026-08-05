from __future__ import annotations

from fastapi import APIRouter

from datum.api.dependencies import Store, Writer
from datum.api.internals.schemas import IngestResponse, SamplesRequest

router = APIRouter(tags=["ingest"])


@router.post("/ingest")
def ingest(body: SamplesRequest, store: Store, resource_id: Writer) -> IngestResponse:
    """Stamp every row with the token's resource_id, then write the batch."""
    return IngestResponse(accepted=store.ingest(body.samples, resource_id))
