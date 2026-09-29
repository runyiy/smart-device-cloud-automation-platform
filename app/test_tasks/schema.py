"""Task request validation and public ORM/UTC response serialization."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.test_tasks.model import TestTaskStatus


class TestTaskCreate(BaseModel):
    """Validate Device reference and normalized task display text."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "device_id": "550e8400-e29b-41d4-a716-446655440000",
                    "name": "Run connectivity diagnostics",
                    "summary": "Check network connectivity and signal quality.",
                }
            ]
        },
    )

    device_id: UUID
    name: str = Field(
        min_length=1,
        max_length=100,
    )
    summary: str | None = Field(
        min_length=1,
        max_length=1000,
        default=None,
    )

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("name must be a string")

        return value.strip()

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: object) -> object:
        if value is None:
            return None

        if not isinstance(value, str):
            raise ValueError("summary must be a string or null")

        return value.strip()


class TestTaskRead(BaseModel):
    """Expose the eight stored task fields without loading relationships."""

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    device_id: UUID
    name: str
    status: TestTaskStatus
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    summary: str | None

    @field_validator(
        "requested_at",
        "started_at",
        "finished_at",
    )
    @classmethod
    def validate_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return value

    @field_serializer(
        "requested_at",
        "started_at",
        "finished_at",
    )
    def serialize_datetime(
        self,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None

        return value.astimezone(UTC)


class TestTaskUpdate(BaseModel):
    """Validate supplied changes; omission preserves fields and null clears summary."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "status": "running",
                },
                {
                    "status": "passed",
                    "summary": "Connectivity diagnostics completed successfully.",
                },
                {
                    "summary": "Updated task notes.",
                },
                {
                    "summary": None,
                },
            ]
        },
    )

    status: TestTaskStatus | None = None
    summary: str | None = Field(
        default=None,
        min_length=1,
        max_length=1000,
    )

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: object) -> object:
        if value is None:
            return None

        if not isinstance(value, str):
            raise ValueError("summary must be a string or null")

        return value.strip()

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: object) -> object:
        if value is None:
            raise ValueError("status cannot be null")

        return value

    @model_validator(mode="after")
    def validate_nonempty_patch(self) -> "TestTaskUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")

        return self
