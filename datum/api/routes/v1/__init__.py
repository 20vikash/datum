from fastapi import APIRouter

from datum.api.routes.v1 import ingest, query, write

router = APIRouter()
router.include_router(ingest.router)
router.include_router(write.router)
router.include_router(query.router)

__all__ = ["router"]
