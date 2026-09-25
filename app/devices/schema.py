"""Validated Device registration input and public response serialization."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.devices.model import DeviceStatus


class DeviceCreate(BaseModel):
    """Strict registration fields with normalized display text."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "examples": [
                {
                    "serial_number": "SN-001",
                    "name": "Lab Sensor 01",
                    "model": "TH-100",
                    "firmware_version": "1.0.0",
                }
            ]
        },
    )

    serial_number: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    name: str
    model: str
    firmware_version: str

    @field_validator("name", "model")
    @classmethod
    def validate_display_fields(cls, value: str) -> str:
        value = value.strip()

        if not 1 <= len(value) <= 100:
            raise ValueError("must contain between 1 and 100 characters")

        return value

    @field_validator("firmware_version")
    @classmethod
    def validate_firmware_version(cls, value: str) -> str:
        value = value.strip()

        if not 1 <= len(value) <= 64:
            raise ValueError("must contain between 1 and 64 characters")

        return value


class DeviceRead(BaseModel):
    """Eight public ORM-backed fields, with non-null JSON timestamps in UTC."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    serial_number: str
    name: str
    model: str
    firmware_version: str
    status: DeviceStatus
    last_seen_at: datetime | None
    created_at: datetime

    @field_serializer(
        "last_seen_at",
        "created_at",
        when_used="json",
    )
    def serialize_datetime_utc(
        self,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None

        return value.astimezone(UTC)
