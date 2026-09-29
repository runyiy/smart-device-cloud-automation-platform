"""create test_tasks table

Revision ID: 237c5f37c6c2
Revises: 68cc8b7ce48b
Create Date: 2026-09-28 22:15:30.069480
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "237c5f37c6c2"
down_revision: str | Sequence[str] | None = "68cc8b7ce48b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add task persistence without changing the existing three business tables.
    op.create_table(
        "test_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "passed",
                "failed",
                "cancelled",
                name="testtaskstatus",
                native_enum=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.String(length=1000), nullable=True),
        sa.CheckConstraint(
            (
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
                "AND finished_at IS NOT NULL)"
            ),
            name="ck_test_tasks_lifecycle_state",
        ),
        sa.CheckConstraint(
            ("status IN ('pending', 'running', 'passed', 'failed', 'cancelled')"),
            name="ck_test_tasks_status_valid",
        ),
        sa.CheckConstraint(
            "char_length(name) >= 1",
            name="ck_test_tasks_name_non_empty",
        ),
        sa.CheckConstraint(
            (
                "finished_at IS NULL "
                "OR ("
                "finished_at >= requested_at "
                "AND (started_at IS NULL OR finished_at >= started_at)"
                ")"
            ),
            name="ck_test_tasks_finished_time",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= requested_at",
            name="ck_test_tasks_started_time",
        ),
        sa.CheckConstraint(
            "summary IS NULL OR char_length(summary) >= 1",
            name="ck_test_tasks_summary_non_empty",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_test_tasks_device_id_devices",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_test_tasks"),
        ),
    )
    op.create_index(
        "ix_test_tasks_device_id_requested_at",
        "test_tasks",
        ["device_id", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_test_tasks_status_requested_at",
        "test_tasks",
        ["status", "requested_at"],
        unique=False,
    )


def downgrade() -> None:
    # Discard task rows only; preserve Device, Telemetry and Alert data.
    op.drop_index("ix_test_tasks_status_requested_at", table_name="test_tasks")
    op.drop_index("ix_test_tasks_device_id_requested_at", table_name="test_tasks")
    op.drop_table("test_tasks")
