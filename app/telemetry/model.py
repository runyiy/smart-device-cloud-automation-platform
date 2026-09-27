"""Telemetry samples with database constraints and explicit Device loading."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.devices.model import Device


class Telemetry(Base):
    """One numeric metric sample belonging to an existing Device."""

    __tablename__ = "telemetry"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        nullable=False,
        default=uuid4,
    )

    device_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "devices.id",
            name="fk_telemetry_device_id_devices",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    device: Mapped["Device"] = relationship(
        "Device",
        lazy="raise",
    )

    metric: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    value: Mapped[float] = mapped_column(
        Double,
        nullable=False,
    )

    unit: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        CheckConstraint(
            "metric ~ '^[A-Za-z0-9._-]+$'",
            name="ck_telemetry_metric_format",
        ),
        CheckConstraint(
            "value > '-Infinity'::double precision "
            "AND value < 'Infinity'::double precision",
            name="ck_telemetry_value_finite",
        ),
        CheckConstraint(
            "char_length(unit) >= 1",
            name="ck_telemetry_unit_non_empty",
        ),
        Index(
            "ix_telemetry_device_id_recorded_at",
            "device_id",
            "recorded_at",
        ),
        Index(
            "ix_telemetry_device_id_metric_recorded_at",
            "device_id",
            "metric",
            "recorded_at",
        ),
    )
