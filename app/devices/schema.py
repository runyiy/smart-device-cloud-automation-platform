"""Validated Device inputs, filters and public response serialization."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

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


class DeviceListQuery(BaseModel):
    """Bounded pagination and exact optional filters from URL query parameters."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    status: Literal["active", "inactive"] | None = None
    model: str | None = None
    serial_number: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    sort_by: Literal["created_at", "serial_number"] = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not 1 <= len(value) <= 100:
            raise ValueError("must contain between 1 and 100 characters")

        return value


class DeviceListResponse(BaseModel):
    """A device page and its pre-pagination filtered total."""

    items: list[DeviceRead]
    total: int
    page: int
    page_size: int


class DeviceUpdate(BaseModel):
    """Validate supplied PATCH fields; omission preserves values, null is invalid."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "Lab Sensor 01",
                    "model": "TH-100",
                    "firmware_version": "1.1.0",
                },
                {
                    "status": "inactive",
                },
            ]
        },
    )

    name: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    status: Literal["active", "inactive"] | None = None

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

    @model_validator(mode="before")
    @classmethod
    def validate_patch_body(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data:
                raise ValueError("PATCH body cannot be empty")

            for field in (
                "name",
                "model",
                "firmware_version",
                "status",
            ):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} cannot be null")

        return data
