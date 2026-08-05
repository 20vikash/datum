from fastapi import APIRouter, Depends

from datum.api.dependencies import get_reader
from datum.api.routes.v1 import ingest, query

router = APIRouter(prefix="/v1")
# Reads are gated on the mount, so a new query route is gated by default.
# Writing needs the resource id itself, so `/ingest` asks for it by name.
router.include_router(query.router, dependencies=[Depends(get_reader)])
router.include_router(ingest.router)

__all__ = ["router"]
