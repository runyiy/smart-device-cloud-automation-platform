"""Alert collection and action endpoints with sanitized domain-error mapping."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette import status

from app.alerts.schema import AlertListQuery, AlertListResponse, AlertRead
from app.alerts.service import AlertNotFoundError, InvalidAlertStateError
from app.alerts.service import (
    acknowledge_alert as acknowledge_alert_service,
)
from app.alerts.service import (
    list_alerts as list_alerts_service,
)
from app.alerts.service import (
    resolve_alert as resolve_alert_service,
)
from app.api.dependencies import get_db_session
from app.api.errors import ErrorResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get(
    "",
    response_model=AlertListResponse,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
        },
    },
)
def list_alerts(
    query: Annotated[AlertListQuery, Query()],
    session: Annotated[Session, Depends(get_db_session)],
) -> AlertListResponse:
    """Return the requested Alert page with its pre-pagination total."""
    alerts, total = list_alerts_service(session=session, query=query)

    return AlertListResponse(
        items=alerts,
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertRead,
    responses={
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
def acknowledge_alert(
    alert_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> AlertRead:
    """Acknowledge an Alert and translate missing/invalid states to HTTP errors."""
    try:
        alert = acknowledge_alert_service(session=session, alert_id=alert_id)

        return AlertRead.model_validate(alert)

    except AlertNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc

    except InvalidAlertStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
        ) from exc


@router.post(
    "/{alert_id}/resolve",
    response_model=AlertRead,
    responses={
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
def resolve_alert(
    alert_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> AlertRead:
    """Resolve an Alert idempotently and translate a missing target to HTTP 404."""
    try:
        alert = resolve_alert_service(session=session, alert_id=alert_id)

        return AlertRead.model_validate(alert)

    except AlertNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc
