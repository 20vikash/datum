from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from datum.api.internals import Identity, MetricProvider

bearer = HTTPBearer(auto_error=False, description="JWT minted by Central.")


def get_provider(request: Request) -> MetricProvider:
    """The provider built at startup. Routes talk to it directly."""
    return request.app.state.provider


def get_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    """Resolve the bearer token to who is calling. Gates the whole /v1 mount."""
    identity = credentials and request.app.state.tokens.resolve(credentials.credentials)
    if not identity:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Unknown or missing token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity

Caller = Annotated[Identity, Depends(get_identity)]


def get_reader(identity: Caller) -> Identity:
    if not identity.can_read:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Token cannot read.")
    return identity


def get_writer(identity: Caller) -> str:
    """The resource id stamped on every written row."""
    if not identity.can_write:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Token cannot write, or names no resource_id."
        )
    return identity.resource_id


Provider = Annotated[MetricProvider, Depends(get_provider)]
Reader = Annotated[Identity, Depends(get_reader)]
Writer = Annotated[str, Depends(get_writer)]
