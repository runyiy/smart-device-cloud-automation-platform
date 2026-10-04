"""Audit persistence with database-enforced storage constraints.

Importing this model registers audit_logs on the shared Base metadata.
The metadata column uses event_metadata because DeclarativeBase.metadata is
reserved. Trusted callers construct safe events and own transaction outcomes.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """A durable event row; add-only repository access is not tamper resistance."""

    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_audit_logs_actor_id_users",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    resource_id: Mapped[UUID] = mapped_column(
        nullable=False,
    )
    event_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        CheckConstraint(
            "char_length(action) BETWEEN 1 AND 64 AND action !~ '[^A-Za-z0-9._-]'",
            name="ck_audit_logs_action_valid",
        ),
        CheckConstraint(
            "resource_type IN ('device', 'telemetry', 'alert', 'test_task')",
            name="ck_audit_logs_resource_type_valid",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_audit_logs_metadata_object",
        ),
        Index(
            "ix_audit_logs_actor_id",
            "actor_id",
        ),
    )
