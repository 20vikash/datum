from fastapi import APIRouter

from datum.api.routes.v1 import ingest

router = APIRouter(prefix="/v1")
router.include_router(ingest.router)

__all__ = ["router"]
