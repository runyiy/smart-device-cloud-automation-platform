"""Version 1 route registration."""

from fastapi import APIRouter

from app.api.v1.schemas import PingResponse

router = APIRouter()


@router.get("/ping", response_model=PingResponse, tags=["system"])
async def ping() -> PingResponse:
    """Return the minimal liveness response for the versioned API."""

    return PingResponse(message="pong")
