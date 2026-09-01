"""Establish the V0 migration baseline.

Revision ID: 0001_v0_baseline
Revises: None
"""

from collections.abc import Sequence

revision: str = "0001_v0_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the initial V0 baseline."""
    pass


def downgrade() -> None:
    """Remove the initial V0 baseline."""
    pass
