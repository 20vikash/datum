from __future__ import annotations

from fastapi import APIRouter, status

from datum.api.dependencies import Caller, Store
from datum.api.internals.schemas import IngestAccepted, IngestRequest

router = APIRouter(tags=["ingest"])


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest(body: IngestRequest, store: Store, caller: Caller) -> IngestAccepted:
    """Write samples straight to the store. No queue in between."""
    return IngestAccepted(accepted=store.ingest(body.samples, caller))
