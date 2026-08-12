from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

from datum.api.dependencies import Admin, Provider, rate_limit
from datum.api.internals.schemas import (
    TERMINATED,
    Resource,
    ResourceId,
    ResourceResponse,
    ResourceUpdate,
)

resource_router = APIRouter(prefix="/resource", tags=["resource"])

TABLE = "resources"
COLUMNS = ("resource_id", "status")

ADMIN_WRITES = 60


@resource_router.post("/add")
def add_resource(
    resource: Resource,
    provider: Provider,
    admin: Admin,
    _: Annotated[None, rate_limit(ADMIN_WRITES)],
) -> ResourceResponse:
    """Register a resource, or move a registered one to a new status."""
    accepted = write(provider, resource.resource_id, resource.status)
    return ResourceResponse(accepted=accepted)


@resource_router.put("/{resource_id}/status")
def update_resource_status(
    resource_id: ResourceId,
    update: ResourceUpdate,
    provider: Provider,
    admin: Admin,
    _: Annotated[None, rate_limit(ADMIN_WRITES)],
) -> ResourceResponse:
    return ResourceResponse(accepted=write(provider, resource_id, update.status))


@resource_router.delete("/{resource_id}")
def delete_resource(
    resource_id: ResourceId,
    provider: Provider,
    admin: Admin,
    _: Annotated[None, rate_limit(ADMIN_WRITES)],
) -> ResourceResponse:
    """Terminated, not removed: datum holds no ALTER grant, and the samples outlive it."""
    return ResourceResponse(accepted=write(provider, resource_id, TERMINATED))


def write(provider: Provider, resource_id: str, status: str) -> int:
    """ReplacingMergeTree keeps the newest row per resource_id, so this is the update too."""
    return provider.insert(TABLE, [{"resource_id": resource_id, "status": status}], COLUMNS)
