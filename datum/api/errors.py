from __future__ import annotations

import logging
import math

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from datum.api.internals import ProviderError, QueryRefused
from datum.api.internals.remote import (
    BodyTooLarge,
    RemoteWriteError,
    TooManyLabels,
    TooManySamples,
    TooManySeries,
)

logger = logging.getLogger("datum")

UNPROCESSABLE = 422

# Every failure a caller can cause, and what they are told. Anything absent is a
# bug and becomes a 500 with a traceback, which is what we want. QueryRefused
# comes first: it is a ProviderError, but it is the caller's fault, not the store's.
STATUS = {
    QueryRefused: 400,
    TooManySamples: 413,
    BodyTooLarge: 413,
    TooManySeries: 413,
    TooManyLabels: 413,
    RemoteWriteError: 400,
    NotImplementedError: 501,
    ProviderError: 503,
}


def install(app: FastAPI) -> None:
    """Point every known failure at its status, so routes never catch."""
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_error)
    for error in STATUS:
        app.add_exception_handler(error, handle_known_error)


def _describe(request: Request) -> str:
    """One line identifying who hit what, so a log entry is actionable."""
    return f"{request.client.host if request.client else '?'} {request.method} {request.url.path}"


async def handle_known_error(request: Request, error: Exception) -> JSONResponse:
    """The exception message is already written for the caller."""
    for kind, status in STATUS.items():
        if isinstance(error, kind):
            logger.warning(
                "bad request %s -> %d %s: %s", _describe(request), status, kind.__name__, error
            )
            return JSONResponse(status_code=status, content={"detail": str(error)})
    raise error


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
    logger.warning("bad request %s -> 422 validation: %s", _describe(request), detail)
    return JSONResponse(status_code=UNPROCESSABLE, content={"detail": detail})


async def handle_http_error(request: Request, error: HTTPException) -> JSONResponse:
    """Auth, permission, and rate-limit refusals. Log them so a flood is visible."""
    logger.warning(
        "bad request %s -> %d: %s",
        _describe(request),
        error.status_code,
        error.detail,
    )
    return JSONResponse(
        status_code=error.status_code, content={"detail": error.detail}, headers=error.headers
    )
