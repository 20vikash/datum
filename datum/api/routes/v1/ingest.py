from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from datum.api.dependencies import Caller, Store
from datum.api.internals import LabelConflict, ProviderError
from datum.api.internals.schemas import IngestAccepted, IngestRequest

router = APIRouter(tags=["ingest"])


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest(body: IngestRequest, store: Store, caller: Caller) -> IngestAccepted:
    """Write samples straight to the store. No queue in between."""
    try:
        accepted = store.ingest(body.samples, caller)
    except LabelConflict as claimed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(claimed)) from claimed
    except NotImplementedError as unwritten:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(unwritten)) from unwritten
    except ProviderError as failure:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(failure)) from failure

    return IngestAccepted(accepted=accepted)
