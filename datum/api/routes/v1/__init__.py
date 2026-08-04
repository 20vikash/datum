from fastapi import APIRouter

from datum.api.routes.v1 import query

router = APIRouter()
router.include_router(query.router)

__all__ = ["router"]
