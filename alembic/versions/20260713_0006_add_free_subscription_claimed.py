"""Track one-time free subscription issuance."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260713_0006"
down_revision = "20260713_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the flag and backfill existing subscribers."""
    op.add_column(
        "users",
        sa.Column("free_subscription_claimed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        UPDATE users
        SET free_subscription_claimed = TRUE
        WHERE EXISTS (
            SELECT 1
            FROM subscriptions
            WHERE subscriptions.user_id = users.id
        )
        """
    )
    op.alter_column("users", "free_subscription_claimed", server_default=None)


def downgrade() -> None:
    """Drop the one-time free subscription flag."""
    op.drop_column("users", "free_subscription_claimed")
