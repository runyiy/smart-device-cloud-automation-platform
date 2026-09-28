"""create alerts table

Revision ID: 68cc8b7ce48b
Revises: 438be65e5187
Create Date: 2026-09-28 15:37:10.112911
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "68cc8b7ce48b"
down_revision: str | Sequence[str] | None = "438be65e5187"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add Alert storage without changing Device or Telemetry tables.
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "warning",
                "critical",
                name="alertseverity",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "acknowledged",
                "resolved",
                name="alertstatus",
                native_enum=False,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            (
                "(status IN ('open', 'acknowledged') "
                "AND resolved_at IS NULL) "
                "OR (status = 'resolved' "
                "AND resolved_at IS NOT NULL)"
            ),
            name="ck_alerts_resolution_state",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_alerts_severity_valid",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name="ck_alerts_status_valid",
        ),
        sa.CheckConstraint(
            "type ~ '^[A-Za-z0-9._-]+$'",
            name="ck_alerts_type_format",
        ),
        sa.CheckConstraint(
            "char_length(message) >= 1",
            name="ck_alerts_message_non_empty",
        ),
        sa.CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= triggered_at",
            name="ck_alerts_resolution_time",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_alerts_device_id_devices",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_alerts"),
        ),
    )

    op.create_index(
        "ix_alerts_device_id_triggered_at",
        "alerts",
        ["device_id", "triggered_at"],
        unique=False,
    )

    op.create_index(
        "ix_alerts_status_triggered_at",
        "alerts",
        ["status", "triggered_at"],
        unique=False,
    )


def downgrade() -> None:
    # Discard Alert rows only; preserve the previous tables and their data.
    op.drop_index("ix_alerts_status_triggered_at", table_name="alerts")
    op.drop_index("ix_alerts_device_id_triggered_at", table_name="alerts")
    op.drop_table("alerts")
