"""Add YooKassa payment provider enum value."""

from __future__ import annotations

from alembic import op

revision = "20260709_0002"
down_revision = "20260709_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Extend payment provider enum with YooKassa."""
    op.execute("ALTER TYPE payment_provider ADD VALUE IF NOT EXISTS 'yookassa'")


def downgrade() -> None:
    """Downgrade is intentionally a no-op for PostgreSQL enum values."""
    return None
