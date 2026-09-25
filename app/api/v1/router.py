"""Version 1 route registration."""

from fastapi import APIRouter

from app.api.v1.schemas import PingResponse
from app.devices.router import router as devices_router

router = APIRouter()


@router.get("/ping", response_model=PingResponse, tags=["system"])
async def ping() -> PingResponse:
    """Return the minimal liveness response for the versioned API."""

    return PingResponse(message="pong")


router.include_router(devices_router)
