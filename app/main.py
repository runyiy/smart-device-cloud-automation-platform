"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1.router import router
from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build one FastAPI application instance.

    The optional Settings argument is the test seam; production startup resolves
    process configuration when no explicit object is supplied.
    """
    resolved_settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        engine = create_db_engine(resolved_settings)
        try:
            session_factory = create_session_factory(engine)

            app.state.session_factory = session_factory

            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(
        router,
        prefix="/api/v1",
    )

    return app
