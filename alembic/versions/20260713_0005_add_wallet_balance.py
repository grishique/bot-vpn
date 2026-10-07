"""Add wallet balance and balance top-up payment support."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0005"
down_revision = "20260712_0004"
branch_labels = None
depends_on = None


payment_purpose_enum = sa.Enum("subscription", "balance_topup", name="payment_purpose")


def upgrade() -> None:
    """Add wallet balance, payment purpose and nullable plan payments."""
    op.add_column(
        "users",
        sa.Column("wallet_balance", sa.Numeric(10, 2), nullable=False, server_default="0"),
    )
    op.alter_column("users", "wallet_balance", server_default=None)

    op.execute("ALTER TYPE payment_provider ADD VALUE IF NOT EXISTS 'balance'")

    payment_purpose_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "payments",
        sa.Column("purpose", payment_purpose_enum, nullable=False, server_default="subscription"),
    )
    op.alter_column("payments", "purpose", server_default=None)
    op.alter_column("payments", "plan_id", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Remove wallet balance support and balance top-up purpose."""
    op.execute("DELETE FROM payments WHERE plan_id IS NULL")
    op.alter_column("payments", "plan_id", existing_type=sa.String(), nullable=False)
    op.drop_column("payments", "purpose")
    payment_purpose_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_column("users", "wallet_balance")
