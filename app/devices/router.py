"""Device registration/detail HTTP handlers and domain-error mapping."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette import status

from app.api.dependencies import get_db_session
from app.api.errors import ErrorResponse
from app.devices.schema import DeviceCreate, DeviceRead
from app.devices.service import (
    DeviceNotFoundError,
    DuplicateSerialNumberError,
    create_device,
    get_device,
)

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post(
    "",
    response_model=DeviceRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
        },
    },
)
def register_device(
    data: DeviceCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> DeviceRead:
    """POST /api/v1/devices -> 201; map duplicate serial errors to HTTP 409."""
    try:
        device = create_device(session=session, data=data)
        return DeviceRead.model_validate(device)

    except DuplicateSerialNumberError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
        ) from exc


@router.get(
    "/{device_id}",
    response_model=DeviceRead,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
        },
    },
)
def read_device(
    device_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> DeviceRead:
    """GET /api/v1/devices/{device_id} -> 200; map missing devices to HTTP 404."""
    try:
        device = get_device(session=session, device_id=device_id)
        return DeviceRead.model_validate(device)

    except DeviceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc
