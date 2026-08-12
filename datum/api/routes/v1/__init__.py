from fastapi import APIRouter

from datum.api.routes.v1 import ingest, logs

router = APIRouter(prefix="/v1")
router.include_router(ingest.router)
router.include_router(logs.router)

__all__ = ["router"]