"""Unversioned liveness and database-readiness endpoints."""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from app.db.readiness import check_database_readiness
from app.db.session import SessionFactory

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Public liveness response."""

    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    """Public database-readiness response."""

    status: Literal["ready", "not_ready"]


def get_session_factory(request: Request) -> SessionFactory:
    """Return the application-owned SessionFactory."""
    return cast(SessionFactory, request.app.state.session_factory)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return process liveness without consulting external dependencies."""
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness(
    response: Response,
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> ReadinessResponse:
    """Return whether PostgreSQL can serve application traffic."""
    if check_database_readiness(session_factory):
        return ReadinessResponse(status="ready")
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="not_ready")
