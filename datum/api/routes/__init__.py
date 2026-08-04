from fastapi import APIRouter, Depends

from datum.api.dependencies import get_identity
from datum.api.routes import query

# One mount: the version prefix and the auth gate, so a new route under it is
# versioned and authenticated without saying so itself.
router = APIRouter()
router.include_router(query.router, prefix="/v1", dependencies=[Depends(get_identity)])

__all__ = ["router"]
