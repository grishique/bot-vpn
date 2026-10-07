"""Add bonus days support to promocodes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260712_0004"
down_revision = "20260712_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the bonus_days column for promocodes."""
    op.add_column(
        "promocodes",
        sa.Column("bonus_days", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("promocodes", "bonus_days", server_default=None)


def downgrade() -> None:
    """Drop the bonus_days column for promocodes."""
    op.drop_column("promocodes", "bonus_days")
