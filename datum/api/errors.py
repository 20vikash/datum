from __future__ import annotations

import math

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

UNPROCESSABLE = 422


def serialisable(value):
    """Same structure, with non-finite floats turned into their names."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: serialisable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialisable(item) for item in value]
    return value


async def handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    """A 422 echoes the input, and NaN is legal in a request but not a response."""
    detail = serialisable(jsonable_encoder(error.errors()))
    return JSONResponse(status_code=UNPROCESSABLE, content={"detail": detail})
