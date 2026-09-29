"""Alert persistence, enum values and database-enforced state consistency."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.devices.model import Device


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Alert(Base):
    """A Device alert; state transitions are handled by the Alert service."""

    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        nullable=False,
        default=uuid4,
    )

    device_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "devices.id",
            name="fk_alerts_device_id_devices",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    device: Mapped[Device] = relationship(
        "Device",
        lazy="raise",
    )

    type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(
            AlertSeverity,
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            length=8,
            create_constraint=False,
        ),
        nullable=False,
    )

    status: Mapped[AlertStatus] = mapped_column(
        SAEnum(
            AlertStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            length=12,
            create_constraint=False,
        ),
        nullable=False,
        default=AlertStatus.OPEN,
        server_default="open",
    )

    message: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    __table_args__ = (
        CheckConstraint(
            "type ~ '^[A-Za-z0-9._-]+$'",
            name="ck_alerts_type_format",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_alerts_severity_valid",
        ),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name="ck_alerts_status_valid",
        ),
        CheckConstraint(
            "char_length(message) >= 1",
            name="ck_alerts_message_non_empty",
        ),
        CheckConstraint(
            "(status IN ('open', 'acknowledged') AND resolved_at IS NULL) "
            "OR (status = 'resolved' AND resolved_at IS NOT NULL)",
            name="ck_alerts_resolution_state",
        ),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= triggered_at",
            name="ck_alerts_resolution_time",
        ),
        Index(
            "ix_alerts_device_id_triggered_at",
            "device_id",
            "triggered_at",
        ),
        Index(
            "ix_alerts_status_triggered_at",
            "status",
            "triggered_at",
        ),
    )
