"""Alert query validation and public ORM/UTC response serialization."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.alerts.model import AlertSeverity, AlertStatus


class AlertRead(BaseModel):
    """Expose stored scalar fields with UTC timestamps, excluding relationships."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: UUID
    type: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    severity: AlertSeverity
    status: AlertStatus
    message: str = Field(
        min_length=1,
        max_length=500,
    )
    triggered_at: datetime
    resolved_at: datetime | None

    @field_validator("triggered_at", "resolved_at")
    @classmethod
    def validate_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return value

    @field_serializer("triggered_at", "resolved_at")
    def serialize_datetime(
        self,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None

        return value.astimezone(UTC)


class AlertListQuery(BaseModel):
    """Bound pagination and validate optional, exact-match collection filters."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    device_id: UUID | None = None
    status: AlertStatus | None = None
    severity: AlertSeverity | None = None
    type: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"
    )
    sort_order: Literal["asc", "desc"] = "desc"


class AlertListResponse(BaseModel):
    """One page and the total matching rows before pagination."""

    items: list[AlertRead]
    total: int
    page: int
    page_size: int
