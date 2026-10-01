"""Create users with fixed roles and database-enforced storage invariants.

Revision ID: ba759824c979
Revises: 237c5f37c6c2
Create Date: 2026-09-30 22:22:59.454473
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ba759824c979"
down_revision: str | Sequence[str] | None = "237c5f37c6c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only users; preserve existing business tables and their data."""
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "role",
            sa.Enum("admin", "operator", "viewer", name="userrole", native_enum=False),
            server_default="viewer",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            " role IN ('admin', 'operator', 'viewer')", name="ck_users_role_valid"
        ),
        sa.CheckConstraint(
            "password_hash ~ '[^[:space:]]'", name="ck_users_password_hash_non_empty"
        ),
        sa.CheckConstraint(
            "char_length(email) >= 1 AND email = lower(btrim(email))",
            name="ck_users_email_normalized",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )


def downgrade() -> None:
    """Remove this revision\'s table without changing earlier business tables."""
    op.drop_table("users")
