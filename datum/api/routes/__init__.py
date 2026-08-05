from fastapi import APIRouter, Depends

from datum.api.dependencies import get_identity
from datum.api.routes import v1

router = APIRouter()
router.include_router(v1.router, dependencies=[Depends(get_identity)])

__all__ = ["router"]
