"""Version 1 route registration."""

from fastapi import APIRouter

from app.alerts.router import router as alert_router
from app.api.v1.schemas import PingResponse
from app.auth.router import router as auth_router
from app.devices.router import router as devices_router
from app.telemetry.router import router as telemetry_router
from app.test_tasks.router import router as test_task_router

router = APIRouter()


@router.get("/ping", response_model=PingResponse, tags=["system"])
async def ping() -> PingResponse:
    """Return the minimal liveness response for the versioned API."""

    return PingResponse(message="pong")


router.include_router(devices_router)
router.include_router(telemetry_router)
router.include_router(alert_router)
router.include_router(test_task_router)
router.include_router(auth_router)
