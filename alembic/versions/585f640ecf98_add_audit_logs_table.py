"""Create audit storage without changing earlier tables

Revision ID: 585f640ecf98
Revises: ba759824c979
Create Date: 2026-10-03 17:04:38.850657
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "585f640ecf98"
down_revision: str | Sequence[str] | None = "ba759824c979"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only audit_logs and its actor index."""
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(action) BETWEEN 1 AND 64 AND action !~ '[^A-Za-z0-9._-]'",
            name="ck_audit_logs_action_valid",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name="ck_audit_logs_metadata_object"
        ),
        sa.CheckConstraint(
            "resource_type IN ('device', 'telemetry', 'alert', 'test_task')",
            name="ck_audit_logs_resource_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_audit_logs_actor_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"], unique=False)


def downgrade() -> None:
    """Remove audit storage while preserving User and business data."""
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_table("audit_logs")
