"""FastAPI application factory."""

from fastapi import FastAPI

from app.api.v1.router import router
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build one FastAPI application instance.

    The optional Settings argument is the test seam; production startup resolves
    process configuration when no explicit object is supplied.
    """
    resolved_settings = settings if settings is not None else get_settings()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        debug=resolved_settings.debug,
    )

    app.include_router(
        router,
        prefix="/api/v1",
    )

    return app
