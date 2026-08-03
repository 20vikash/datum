from __future__ import annotations

from fastapi import FastAPI

from ..config import Settings
from .routes import router

TITLE = "datum"
VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the `datum-api` application."""
    app = FastAPI(title=TITLE, version=VERSION)
    app.state.settings = settings or Settings.from_env()
    app.include_router(router)
    return app
