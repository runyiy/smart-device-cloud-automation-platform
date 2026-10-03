"""Strict login input and allowlisted authentication response contracts."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_serializer,
    field_validator,
)

from app.users.model import UserRole


class LoginRequest(BaseModel):
    """JSON credentials; normalize only email and never transform the password."""

    model_config = ConfigDict(extra="forbid", strict=True)

    email: str
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Trim/lower and require a nonblank identifier of at most 254 chars."""
        value = value.strip().lower()

        if not 1 <= len(value) <= 254:
            raise ValueError("email must be between 1 and 254 characters")

        return value


class TokenResponse(BaseModel):
    """Return one short-lived bearer access token; no refresh token."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"


class CurrentUserRead(BaseModel):
    """Five public fields; password_hash never enters this response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime

    @field_serializer("created_at", when_used="json")
    def serialize_created_at(self, value: datetime) -> datetime:
        """Serialize the persisted aware timestamp in UTC."""
        return value.astimezone(UTC)
