"""Initial project schema."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260709_0001"
down_revision = None
branch_labels = None
depends_on = None


user_role = postgresql.ENUM("user", "admin", name="user_role", create_type=False)
subscription_status = postgresql.ENUM(
    "pending",
    "active",
    "expired",
    "cancelled",
    name="subscription_status",
    create_type=False,
)
payment_status = postgresql.ENUM(
    "pending",
    "paid",
    "failed",
    "refunded",
    name="payment_status",
    create_type=False,
)
payment_provider = postgresql.ENUM("telegram", name="payment_provider", create_type=False)


def upgrade() -> None:
    """Create the initial database schema."""
    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    subscription_status.create(bind, checkfirst=True)
    payment_status.create(bind, checkfirst=True)
    payment_provider.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("referral_code", sa.String(length=32), nullable=False),
        sa.Column("referred_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_banned", sa.Boolean(), nullable=False),
        sa.Column("bonus_days_balance", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["referred_by_id"], ["users.id"]),
        sa.UniqueConstraint("referral_code"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=False)
    op.create_index(op.f("ix_users_referral_code"), "users", ["referral_code"], unique=False)

    op.create_table(
        "vpn_servers",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("panel_url", sa.String(length=255), nullable=False),
        sa.Column("panel_username", sa.String(length=255), nullable=False),
        sa.Column("panel_password_encrypted", sa.Text(), nullable=False),
        sa.Column("inbound_id", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("public_key", sa.String(length=255), nullable=False),
        sa.Column("sni", sa.String(length=255), nullable=False),
        sa.Column("short_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("spider_x", sa.String(length=255), nullable=False),
        sa.Column("flow", sa.String(length=64), nullable=False),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("remark_prefix", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "plans",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("price_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("traffic_limit_gb", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "promocodes",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("discount_percent", sa.Integer(), nullable=True),
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("max_usages", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_promocodes_code"), "promocodes", ["code"], unique=False)

    op.create_table(
        "subscriptions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("xui_client_id", sa.String(length=64), nullable=True),
        sa.Column("client_email", sa.String(length=255), nullable=False),
        sa.Column("vless_uuid", sa.String(length=64), nullable=False),
        sa.Column("access_url", sa.Text(), nullable=True),
        sa.Column("status", subscription_status, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminder_sent_3d", sa.Boolean(), nullable=False),
        sa.Column("reminder_sent_1d", sa.Boolean(), nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.ForeignKeyConstraint(["server_id"], ["vpn_servers.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("client_email"),
        sa.UniqueConstraint("vless_uuid"),
        sa.UniqueConstraint("xui_client_id"),
    )
    op.create_index(op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"], unique=False)

    op.create_table(
        "referrals",
        sa.Column("referrer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("referee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reward_days", sa.Integer(), nullable=False),
        sa.Column("reward_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["referee_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["referrer_id"], ["users.id"]),
        sa.UniqueConstraint("referee_id", name="uq_referral_referee"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"], unique=False)

    op.create_table(
        "payments",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("promocode_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", payment_provider, nullable=False),
        sa.Column("status", payment_status, nullable=False),
        sa.Column("invoice_payload", sa.String(length=255), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("telegram_charge_id", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("amount_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.ForeignKeyConstraint(["promocode_id"], ["promocodes.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("invoice_payload"),
    )
    op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"], unique=False)


def downgrade() -> None:
    """Drop the initial database schema."""
    op.drop_index(op.f("ix_payments_user_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_index(op.f("ix_audit_logs_user_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("referrals")
    op.drop_index(op.f("ix_subscriptions_user_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index(op.f("ix_promocodes_code"), table_name="promocodes")
    op.drop_table("promocodes")
    op.drop_table("plans")
    op.drop_table("vpn_servers")
    op.drop_index(op.f("ix_users_referral_code"), table_name="users")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    payment_provider.drop(bind, checkfirst=True)
    payment_status.drop(bind, checkfirst=True)
    subscription_status.drop(bind, checkfirst=True)
    user_role.drop(bind, checkfirst=True)
