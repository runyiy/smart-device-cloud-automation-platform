"""Device persistence model and database-level field constraints.

Field and constraint contracts are defined in CURRENT_STAGE.md.
Importing this module registers the devices table with the shared Base metadata.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeviceStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        nullable=False,
        default=uuid4,
    )

    serial_number: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    firmware_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[DeviceStatus] = mapped_column(
        SAEnum(
            DeviceStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            length=8,
            create_constraint=False,
        ),
        nullable=False,
        default=DeviceStatus.ACTIVE,
        server_default="active",
    )

    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        CheckConstraint(
            "serial_number ~ '^[A-Za-z0-9._-]+$'",
            name="check_devices_serial_number_format",
        ),
        CheckConstraint(
            "char_length(name) >= 1",
            name="ck_devices_name_non_empty",
        ),
        CheckConstraint(
            "char_length(model) >= 1",
            name="ck_devices_model_non_empty",
        ),
        CheckConstraint(
            "char_length(firmware_version) >= 1",
            name="ck_devices_firmware_version_non_empty",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_devices_status_valid",
        ),
    )
