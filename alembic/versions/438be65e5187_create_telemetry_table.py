"""create telemetry table

Revision ID: 438be65e5187
Revises: f4502b63c0be
Create Date: 2026-09-26 22:57:55.902270
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "438be65e5187"
down_revision: str | Sequence[str] | None = "f4502b63c0be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add sample storage without changing the existing Device table.
    op.create_table(
        "telemetry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "metric ~ '^[A-Za-z0-9._-]+$'", name="ck_telemetry_metric_format"
        ),
        sa.CheckConstraint(
            "value > '-Infinity'::double precision "
            "AND value < 'Infinity'::double precision",
            name="ck_telemetry_value_finite",
        ),
        sa.CheckConstraint(
            "char_length(unit) >= 1", name="ck_telemetry_unit_non_empty"
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_telemetry_device_id_devices",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry")),
    )
    op.create_index(
        "ix_telemetry_device_id_metric_recorded_at",
        "telemetry",
        ["device_id", "metric", "recorded_at"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_device_id_recorded_at",
        "telemetry",
        ["device_id", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    # Discard telemetry samples only; preserve Device rows and the previous head.
    op.drop_index("ix_telemetry_device_id_recorded_at", table_name="telemetry")
    op.drop_index("ix_telemetry_device_id_metric_recorded_at", table_name="telemetry")
    op.drop_table("telemetry")
