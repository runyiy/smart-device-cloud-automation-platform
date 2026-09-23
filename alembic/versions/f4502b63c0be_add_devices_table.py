"""add devices table

Revision ID: f4502b63c0be
Revises: 0001_v0_baseline
Create Date: 2026-09-23 14:34:50.183280
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4502b63c0be"
down_revision: str | Sequence[str] | None = "0001_v0_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create only the Device table and its database constraints.
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("serial_number", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("firmware_version", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", name="devicestatus", native_enum=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "serial_number ~ '^[A-Za-z0-9._-]+$'",
            name="check_devices_serial_number_format",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name="ck_devices_status_valid"
        ),
        sa.CheckConstraint(
            "char_length(firmware_version) >= 1",
            name="ck_devices_firmware_version_non_empty",
        ),
        sa.CheckConstraint(
            "char_length(model) >= 1", name="ck_devices_model_non_empty"
        ),
        sa.CheckConstraint("char_length(name) >= 1", name="ck_devices_name_non_empty"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.UniqueConstraint("serial_number", name=op.f("uq_devices_serial_number")),
    )


def downgrade() -> None:
    # Return to the table-free V0 baseline; this drops any stored device rows.
    op.drop_table("devices")
