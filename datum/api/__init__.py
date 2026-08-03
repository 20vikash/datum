"""HTTP endpoints. Routes stay thin; behaviour lives in the modules they call."""

from .app import create_app

__all__ = ["create_app"]
