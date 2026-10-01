"""User persistence with one fixed role and an opaque encoded password hash."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(StrEnum):
    """One fixed role per User; this Task does not implement permission checks."""

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class User(Base):
    """A persisted account; credential processing belongs to authentication."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        nullable=False,
        default=uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(254),
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            length=8,
            create_constraint=False,
        ),
        nullable=False,
        default=UserRole.VIEWER,
        server_default="viewer",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        CheckConstraint(
            # Require a non-whitespace character, not a specific hash algorithm.
            "password_hash ~ '[^[:space:]]'",
            name="ck_users_password_hash_non_empty",
        ),
        CheckConstraint(
            "char_length(email) >= 1 AND email = lower(btrim(email))",
            name="ck_users_email_normalized",
        ),
        CheckConstraint(
            " role IN ('admin', 'operator', 'viewer')", name="ck_users_role_valid"
        ),
        UniqueConstraint(
            "email",
            name="uq_users_email",
        ),
    )
