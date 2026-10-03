"""Telemetry HTTP handlers and sanitized domain-error mapping."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette import status

from app.api.dependencies import get_db_session
from app.api.errors import ErrorResponse
from app.auth.authorization import require_roles
from app.devices.service import DeviceNotFoundError
from app.telemetry.schema import (
    TelemetryCreate,
    TelemetryListQuery,
    TelemetryListResponse,
    TelemetryRead,
)
from app.telemetry.service import InactiveDeviceError, ingest_telemetry, list_telemetry
from app.users.model import UserRole

router = APIRouter(prefix="/devices/{device_id}/telemetry", tags=["telemetry"])


@router.post(
    "",
    response_model=TelemetryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            require_roles(
                UserRole.ADMIN,
                UserRole.OPERATOR,
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
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
        },
    },
)
def post_telemetry(
    device_id: UUID,
    data: TelemetryCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> TelemetryRead:
    """POST collection -> 201; missing/inactive Device -> 404/409."""
    try:
        telemetry = ingest_telemetry(
            session=session,
            device_id=device_id,
            data=data,
        )

        return TelemetryRead.model_validate(telemetry)

    except DeviceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc

    except InactiveDeviceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
        ) from exc


@router.get(
    "",
    response_model=TelemetryListResponse,
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
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
        },
    },
)
def get_telemetry_collection(
    device_id: UUID,
    query: Annotated[TelemetryListQuery, Query()],
    session: Annotated[Session, Depends(get_db_session)],
) -> TelemetryListResponse:
    """GET collection -> 200 page; read parameters from the URL, not a body."""
    try:
        telemetries, total = list_telemetry(
            session=session,
            device_id=device_id,
            query=query,
        )

        return TelemetryListResponse(
            items=telemetries,
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    except DeviceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc
