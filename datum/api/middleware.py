from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from datum.config.limits import MAX_BODY

CARRIES_BODY = frozenset({"POST", "PUT", "PATCH"})

LENGTH_REQUIRED = 411
TOO_LARGE = 413


class BodyLimit:
    """Refuse an oversized body before anything reads it.

    ASGI rather than a dependency: FastAPI reads the body before solving
    dependencies. No declared length is refused, or the limit is optional.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        refusal = self.get_refusal(scope) if scope["type"] == "http" else None
        await (refusal or self.app)(scope, receive, send)

    def get_refusal(self, scope: Scope) -> JSONResponse | None:
        """The response to send instead of routing, or None to carry on."""
        if scope["method"] not in CARRIES_BODY:
            return None

        declared = Headers(scope=scope).get("content-length")
        if declared is None or not declared.isdigit():
            return JSONResponse(
                status_code=LENGTH_REQUIRED,
                content={"detail": "Content-Length is required, and must be a number."},
            )
        if int(declared) > self.max_bytes:
            return JSONResponse(
                status_code=TOO_LARGE,
                content={"detail": f"Body is {declared} bytes; the cap is {self.max_bytes}."},
            )
        return None
