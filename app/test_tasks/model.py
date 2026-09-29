"""Manual task persistence with database-enforced state and timestamp consistency."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.devices.model import Device


class TestTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TestTask(Base):
    """A Device task snapshot; application lifecycle transitions belong to T10."""

    __tablename__ = "test_tasks"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        nullable=False,
        default=uuid4,
    )

    device_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "devices.id",
            name="fk_test_tasks_device_id_devices",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    device: Mapped["Device"] = relationship(
        "Device",
        lazy="raise",
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[TestTaskStatus] = mapped_column(
        Enum(
            TestTaskStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            length=9,
            create_constraint=False,
        ),
        nullable=False,
        default=TestTaskStatus.PENDING,
        server_default="pending",
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    summary: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    __table_args__ = (
        CheckConstraint(
            "char_length(name) >= 1",
            name="ck_test_tasks_name_non_empty",
        ),
        CheckConstraint(
            "status IN ('pending', 'running','passed','failed','cancelled')",
            name="ck_test_tasks_status_valid",
        ),
        CheckConstraint(
            "summary IS NULL OR char_length(summary) >= 1",
            name="ck_test_tasks_summary_non_empty",
        ),
        CheckConstraint(
            "(status = 'pending' "
            "AND started_at IS NULL "
            "AND finished_at IS NULL) "
            "OR (status = 'running' "
            "AND started_at IS NOT NULL "
            "AND finished_at IS NULL) "
            "OR ((status = 'passed' OR status = 'failed') "
            "AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL) "
            "OR (status = 'cancelled' "
            "AND finished_at IS NOT NULL)",
            name="ck_test_tasks_lifecycle_state",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= requested_at",
            name="ck_test_tasks_started_time",
        ),
        CheckConstraint(
            (
                "finished_at IS NULL "
                "OR ("
                "finished_at >= requested_at "
                "AND (started_at IS NULL OR finished_at >= started_at)"
                ")"
            ),
            name="ck_test_tasks_finished_time",
        ),
        Index(
            "ix_test_tasks_device_id_requested_at",
            "device_id",
            "requested_at",
        ),
        Index(
            "ix_test_tasks_status_requested_at",
            "status",
            "requested_at",
        ),
    )
