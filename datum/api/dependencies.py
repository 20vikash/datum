from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from datum.api.internals import Identity, MetricStore

bearer = HTTPBearer(auto_error=False, description="Token minted by Central.")


def get_store(request: Request) -> MetricStore:
    """The store built at startup."""
    return request.app.state.store


def get_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    """Resolve the bearer token to who is calling. Identity never comes from the body."""
    identity = credentials and request.app.state.tokens.resolve(credentials.credentials)
    if not identity:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Unknown or missing token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity


Store = Annotated[MetricStore, Depends(get_store)]
Caller = Annotated[Identity, Depends(get_identity)]
