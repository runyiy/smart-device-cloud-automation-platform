"""Validated telemetry inputs, query filters and UTC response serialization."""

import math
import re
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

_NUMERIC_TIMESTAMP_PATTERN = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
)


class TelemetryCreate(BaseModel):
    """One sample input; full field rules are specified in CURRENT_STAGE.md."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "examples": [
                {
                    "metric": "temperature",
                    "value": 23.5,
                    "unit": "°C",
                    "recorded_at": "2026-09-26T10:00:00Z",
                }
            ]
        },
    )

    metric: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    value: float
    unit: str = Field(
        min_length=1,
        max_length=32,
    )
    recorded_at: datetime = Field(strict=False)

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("value must be a number")

        try:
            number = float(value)
        except OverflowError as exc:
            raise ValueError("value is too large") from exc

        if not math.isfinite(number):
            raise ValueError("value must be finite")

        return number

    @field_validator("unit", mode="before")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("unit must be a string")

        return value.strip()

    @field_validator("recorded_at", mode="before")
    @classmethod
    def validate_recorded_at_input(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("numeric timestamps are not allowed")

        if isinstance(value, (int, float)):
            raise ValueError("numeric timestamps are not allowed")

        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            if _NUMERIC_TIMESTAMP_PATTERN.fullmatch(value.strip()):
                raise ValueError("numeric timestamps are not allowed")

            return value

        raise ValueError("recorded_at must be a datetime")

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone")

        try:
            return value.astimezone(UTC)
        except OverflowError as exc:
            raise ValueError(
                "recorded_at is outside the supported datetime range"
            ) from exc


class TelemetryRead(BaseModel):
    """Public sample fields only; never include the Device relationship."""

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    device_id: UUID
    metric: str
    value: float
    unit: str
    recorded_at: datetime
    received_at: datetime

    @field_serializer(
        "recorded_at",
        "received_at",
        when_used="json",
    )
    def serialize_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class TelemetryListQuery(BaseModel):
    """Validated query filters; public time aliases are from and to."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    metric: str | None = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
        default=None,
    )
    from_time: datetime | None = Field(default=None, alias="from")
    to_time: datetime | None = Field(default=None, alias="to")
    sort_order: Literal["asc", "desc"] = "desc"

    @field_validator("from_time", "to_time", mode="before")
    @classmethod
    def validate_recorded_at_input(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("recorded_at must be an ISO 8601 datetime")

        if isinstance(value, (int, float)):
            raise ValueError("numeric timestamps are not allowed")

        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            if _NUMERIC_TIMESTAMP_PATTERN.fullmatch(value.strip()):
                raise ValueError("numeric timestamps are not allowed")

            return value

        raise ValueError("recorded_at must be an ISO 8601 datetime")

    @field_validator("to_time", "from_time")
    @classmethod
    def validate_time_bound(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include a timezone")

        try:
            return value.astimezone(UTC)
        except OverflowError as exc:
            raise ValueError("datetime is outside the supported range") from exc

    @model_validator(mode="after")
    def validate_time_range(self) -> "TelemetryListQuery":
        if (
            self.from_time is not None
            and self.to_time is not None
            and self.from_time > self.to_time
        ):
            raise ValueError("from must be less than or equal to to")

        return self


class TelemetryListResponse(BaseModel):
    """One page plus its pre-pagination filtered total."""

    items: list[TelemetryRead]
    total: int
    page: int
    page_size: int
