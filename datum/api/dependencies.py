from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from datum.api.internals import Identity, LogProvider, MetricProvider
from datum.config.limits import MAX_REQUESTS, RATE_PERIOD

bearer = HTTPBearer(
    auto_error=False,
    description="JWT minted by Central.",
)


def get_provider(request: Request) -> MetricProvider:
    """The provider built at startup. Routes talk to it directly."""
    return request.app.state.provider


def get_log_provider(request: Request) -> LogProvider:
    """The logs provider built at startup. Sibling of `get_provider`."""
    return request.app.state.log_provider


def get_identity(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer),
    ],
) -> Identity:
    identity = credentials and request.app.state.tokens.resolve(
        credentials.credentials
    )

    if not identity:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Unknown or missing token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return identity


Caller = Annotated[Identity, Depends(get_identity)]


def rate_limit(
    limit: int = MAX_REQUESTS,
    period: float = RATE_PERIOD,
):
    """Allow route based rate limiting via the token."""

    def spend(request: Request, identity: Caller) -> None:
        route = request.scope["route"].path
        retry_after = request.app.state.limiter.get_retry_after(
            identity.resource_id,
            route,
            limit,
            period,
        )

        if retry_after:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests.",
                headers={"Retry-After": str(retry_after)},
            )

    return Depends(spend)


def get_writer(identity: Caller) -> str:
    """The resource id stamped on every written row."""
    if not identity.can_write:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Token cannot write.",
        )

    return identity.resource_id


Provider = Annotated[MetricProvider, Depends(get_provider)]
LogStore = Annotated[LogProvider, Depends(get_log_provider)]
Writer = Annotated[str, Depends(get_writer)]