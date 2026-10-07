"""Celery application factory."""

from __future__ import annotations

from pathlib import Path

from celery import Celery
from celery.schedules import crontab

from app.config.settings import get_settings

settings = get_settings()
beat_schedule_file = Path(settings.celery_beat_schedule_file)
beat_schedule_file.parent.mkdir(parents=True, exist_ok=True)

celery_app = Celery(
    "vpn_saas_bot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.scheduler.tasks"],
)
celery_app.conf.timezone = settings.timezone
celery_app.conf.task_ignore_result = True
celery_app.conf.beat_schedule_filename = str(beat_schedule_file)
celery_app.conf.beat_schedule = {
    "reconcile-yookassa-payments-every-minute": {
        "task": "app.scheduler.tasks.reconcile_yookassa_payments_task",
        "schedule": crontab(minute="*"),
    },
    "send-expiration-reminders-hourly": {
        "task": "app.scheduler.tasks.send_expiration_reminders_task",
        "schedule": crontab(minute=0),
    },
    "expire-subscriptions-every-15-minutes": {
        "task": "app.scheduler.tasks.expire_subscriptions_task",
        "schedule": crontab(minute="*/15"),
    },
    "check-traffic-limits-every-10-minutes": {
        "task": "app.scheduler.tasks.check_traffic_limits_task",
        "schedule": crontab(minute="*/10"),
    },
}

celery_app.autodiscover_tasks(["app.scheduler"])
