"""Device HTTP handlers and domain-error mapping."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette import status

from app.api.dependencies import get_db_session
from app.api.errors import ErrorResponse
from app.auth.authorization import require_roles
from app.devices.schema import (
    DeviceCreate,
    DeviceListQuery,
    DeviceListResponse,
    DeviceRead,
    DeviceUpdate,
)
from app.devices.service import (
    DeviceNotFoundError,
    DuplicateSerialNumberError,
    InvalidDeviceStateError,
    create_device,
    get_device,
    list_devices,
    update_device,
)
from app.users.model import User, UserRole

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post(
    "",
    response_model=DeviceRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
        },
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
    actor: Annotated[
        User,
        Depends(
            require_roles(
                UserRole.ADMIN,
            )
        ),
    ],
) -> DeviceRead:
    """POST /api/v1/devices -> 201; map duplicate serial errors to HTTP 409."""
    try:
        device = create_device(session=session, data=data, actor_id=actor.id)
        return DeviceRead.model_validate(device)

    except DuplicateSerialNumberError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
        ) from exc


@router.get(
    "",
    response_model=DeviceListResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[
        Depends(
            require_roles(
                UserRole.ADMIN,
                UserRole.OPERATOR,
                UserRole.VIEWER,
            )
        )
    ],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
        },
    },
)
def list_device_collection(
    query: Annotated[DeviceListQuery, Query()],
    session: Annotated[Session, Depends(get_db_session)],
) -> DeviceListResponse:
    """GET /api/v1/devices; parse query parameters, not a JSON request body."""
    (devices, total) = list_devices(session=session, query=query)

    return DeviceListResponse(
        items=devices, total=total, page=query.page, page_size=query.page_size
    )


@router.patch(
    "/{device_id}",
    response_model=DeviceRead,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
        },
    },
)
def patch_device(
    device_id: UUID,
    data: DeviceUpdate,
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[
        User,
        Depends(
            require_roles(
                UserRole.ADMIN,
            )
        ),
    ],
) -> DeviceRead:
    """PATCH /api/v1/devices/{device_id}; map missing/state errors to 404/409."""
    try:
        device = update_device(
            session=session, device_id=device_id, data=data, actor_id=actor.id
        )
        return DeviceRead.model_validate(device)

    except DeviceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc

    except InvalidDeviceStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
        ) from exc


@router.get(
    "/{device_id}",
    response_model=DeviceRead,
    dependencies=[
        Depends(
            require_roles(
                UserRole.ADMIN,
                UserRole.OPERATOR,
                UserRole.VIEWER,
            )
        )
    ],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
        },
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
