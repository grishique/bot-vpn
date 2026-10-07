"""Environment-backed application settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object loaded from the .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="VPN SaaS Bot", alias="APP_NAME")
    app_env: str = Field(default="production", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_secret_key: str = Field(alias="APP_SECRET_KEY")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    timezone: str = Field(default="Asia/Yekaterinburg", alias="TIMEZONE")

    database_url: str = Field(alias="DATABASE_URL")
    sync_database_url: str = Field(alias="SYNC_DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")
    celery_broker_url: str = Field(alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(alias="CELERY_RESULT_BACKEND")
    celery_beat_schedule_file: str = Field(
        default="work/celerybeat-schedule",
        alias="CELERY_BEAT_SCHEDULE_FILE",
    )

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_provider_token: str = Field(default="", alias="TELEGRAM_PROVIDER_TOKEN")
    telegram_webhook_base: str = Field(alias="TELEGRAM_WEBHOOK_BASE")
    telegram_webhook_path: str = Field(alias="TELEGRAM_WEBHOOK_PATH")
    telegram_webhook_secret: str = Field(alias="TELEGRAM_WEBHOOK_SECRET")
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")
    telegram_support_url: str = Field(default="", alias="TELEGRAM_SUPPORT_URL")
    telegram_required_channel_username: str = Field(default="", alias="TELEGRAM_REQUIRED_CHANNEL_USERNAME")
    telegram_required_channel_url: str = Field(default="", alias="TELEGRAM_REQUIRED_CHANNEL_URL")
    support_username: str = Field(default="", alias="SUPPORT_USERNAME")
    support_email: str = Field(default="", alias="SUPPORT_EMAIL")
    support_ticket_url: str = Field(default="", alias="SUPPORT_TICKET_URL")
    telegram_admin_ids: str = Field(default="", alias="TELEGRAM_ADMIN_IDS")
    telegram_parse_mode: str = Field(default="HTML", alias="TELEGRAM_PARSE_MODE")
    telegram_use_polling: bool = Field(default=False, alias="TELEGRAM_USE_POLLING")
    telegram_set_commands_on_startup: bool = Field(default=True, alias="TELEGRAM_SET_COMMANDS_ON_STARTUP")
    telegram_set_webhook_on_startup: bool = Field(default=True, alias="TELEGRAM_SET_WEBHOOK_ON_STARTUP")
    privacy_policy_url: str = Field(
        default="https://your-domain.example.com/privacy",
        alias="PRIVACY_POLICY_URL",
    )
    terms_of_service_url: str = Field(
        default="https://your-domain.example.com/terms",
        alias="TERMS_OF_SERVICE_URL",
    )

    payment_provider: str = Field(default="telegram", alias="PAYMENT_PROVIDER")
    payment_currency: str = Field(default="RUB", alias="PAYMENT_CURRENCY")
    yookassa_shop_id: str = Field(default="", alias="YOOKASSA_SHOP_ID")
    yookassa_secret_key: str = Field(default="", alias="YOOKASSA_SECRET_KEY")
    yookassa_return_url: str = Field(default="", alias="YOOKASSA_RETURN_URL")
    yookassa_webhook_secret: str = Field(default="", alias="YOOKASSA_WEBHOOK_SECRET")
    payment_success_text: str = Field(
        default="Платёж прошёл успешно. Подписка активирована.",
        alias="PAYMENT_SUCCESS_TEXT",
    )

    default_server_id: str | None = Field(default=None, alias="DEFAULT_SERVER_ID")
    default_referral_reward_days: int = Field(
        default=7,
        alias="DEFAULT_REFERRAL_REWARD_DAYS",
    )
    default_promocode_max_uses: int = Field(
        default=100,
        alias="DEFAULT_PROMOCODE_MAX_USES",
    )
    default_promocode_discount_percent: int = Field(
        default=10,
        alias="DEFAULT_PROMOCODE_DISCOUNT_PERCENT",
    )

    reminder_days_before_1: int = Field(default=1, alias="REMINDER_DAYS_BEFORE_1")
    reminder_days_before_2: int = Field(default=3, alias="REMINDER_DAYS_BEFORE_2")
    subscription_grace_hours: int = Field(default=0, alias="SUBSCRIPTION_GRACE_HOURS")

    qr_box_size: int = Field(default=8, alias="QR_BOX_SIZE")
    qr_border: int = Field(default=2, alias="QR_BORDER")

    @computed_field  # type: ignore[misc]
    @property
    def telegram_webhook_url(self) -> str:
        """Return the complete webhook URL."""
        return f"{self.telegram_webhook_base.rstrip('/')}{self.telegram_webhook_path}"

    @computed_field  # type: ignore[misc]
    @property
    def effective_public_base_url(self) -> str:
        """Return a public base URL for subscription links."""
        if self.public_base_url.strip():
            return self.public_base_url.rstrip("/")
        if self.telegram_webhook_base and "your-domain.example.com" not in self.telegram_webhook_base:
            return self.telegram_webhook_base.rstrip("/")
        return "http://127.0.0.1"

    @computed_field  # type: ignore[misc]
    @property
    def admin_ids(self) -> list[int]:
        """Return a parsed list of Telegram administrator ids."""
        values = [item.strip() for item in self.telegram_admin_ids.split(",") if item.strip()]
        return [int(item) for item in values]

    @computed_field  # type: ignore[misc]
    @property
    def support_username_url(self) -> str:
        """Return a Telegram URL for the support username when configured."""
        username = self.support_username.strip().lstrip("@")
        return f"https://t.me/{username}" if username else ""


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
