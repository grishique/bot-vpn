"""Add Codex Pass level tracking to users."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260712_0003"
down_revision = "20260709_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the Codex Pass level column and backfill existing users."""
    op.add_column(
        "users",
        sa.Column("codex_pass_level", sa.Integer(), nullable=False, server_default="0"),
    )

    op.execute(
        """
        WITH referral_counts AS (
            SELECT
                referrer_id,
                COUNT(*) AS activated_count
            FROM referrals
            WHERE reward_applied_at IS NOT NULL
            GROUP BY referrer_id
        )
        UPDATE users
        SET codex_pass_level = CASE
            WHEN referral_counts.activated_count >= 18 THEN 3
            WHEN referral_counts.activated_count >= 8 THEN 2
            WHEN referral_counts.activated_count >= 3 THEN 1
            ELSE 0
        END
        FROM referral_counts
        WHERE users.id = referral_counts.referrer_id
        """
    )

    op.alter_column("users", "codex_pass_level", server_default=None)


def downgrade() -> None:
    """Drop the Codex Pass level column."""
    op.drop_column("users", "codex_pass_level")
