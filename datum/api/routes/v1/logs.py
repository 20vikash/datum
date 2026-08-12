from __future__ import annotations

from fastapi import APIRouter, Request

from datum.api.dependencies import LogStore, Writer
from datum.api.internals.schemas import IngestResponse, LogLine, LogLineRequest

router = APIRouter(tags=["logs"])


@router.post("/logs/ingest")
async def ingest(
    request: Request,
    store: LogStore,
    resource_id: Writer,
) -> IngestResponse:
    body = await request.json()

    req = LogLineRequest.model_validate(body)
    lines = req.lines

    return IngestResponse(
        accepted=store.ingest(get_rows(lines, resource_id))
    )


def get_rows(
    lines: list[LogLine],
    resource_id: str,
) -> list[dict]:
    return [line.get_row(resource_id) for line in lines]