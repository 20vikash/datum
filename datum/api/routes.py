from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Liveness probe. Says nothing about the metrics store."""
    return {"status": "ok"}
