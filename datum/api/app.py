from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from datum.api.errors import handle_validation_error
from datum.api.internals import MetricStore, TokenStore, get_provider
from datum.api.routes import router
from datum.config import Settings

TITLE = "datum"
VERSION = "0.1.0"

TAGS = [
    {"name": "ingest", "description": "Producers push numbers. Identity comes from the token."},
    {"name": "query", "description": "Read numbers back with SQL. One SELECT, one PromQL query."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    provider = get_provider(settings.backend, url=settings.url)
    app.state.store = MetricStore(provider, dialect=settings.dialect, mode=settings.mode)
    yield
    app.state.store = None


def create_app(settings: Settings | None = None, tokens: TokenStore | None = None) -> FastAPI:
    """Build the `datum-api` application.

    `tokens` defaults to whatever `DATUM_TOKENS` holds. With none set, every
    /v1 call is a 401.
    """
    app = FastAPI(
        title=TITLE,
        version=VERSION,
        openapi_tags=TAGS,
        openapi_url="/v1/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings or Settings.from_env()
    app.state.tokens = tokens or TokenStore.from_env()
    app.state.store = None
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.include_router(router)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        """Liveness probe. Unversioned, so a future /v2 never breaks it."""
        return {"status": "ok"}

    return app
