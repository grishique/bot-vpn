# Запуск и настройка

## Docker: polling

Скопируйте `.env.example` в `.env`, заполните токен бота и параметры сервиса. Используйте:

```dotenv
TELEGRAM_USE_POLLING=true
TELEGRAM_SET_WEBHOOK_ON_STARTUP=false
```

```bash
docker compose up -d --build
```

Внутри Compose адреса БД и Redis — `postgres` и `redis`. Контейнер `bot` получает сообщения через polling; `app` обслуживает API. Не запускайте второй polling-процесс с тем же токеном.

## Python на компьютере

Установите Python 3.13+ и зависимости (`python -m pip install .`). Запустите инфраструктуру с локальным override:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d postgres redis
```

В `.env` замените контейнерные адреса на `127.0.0.1`:

```dotenv
DATABASE_URL=postgresql+asyncpg://vpn_user:YOUR_PASSWORD@127.0.0.1:5432/vpn_saas
SYNC_DATABASE_URL=postgresql+psycopg://vpn_user:YOUR_PASSWORD@127.0.0.1:5432/vpn_saas
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
```

Приложение использует именно URL-переменные: изменение только `POSTGRES_HOST` или `REDIS_HOST` их не пересобирает. Для специальных символов в пароле используйте URL-кодирование в строках подключения.

```bash
alembic upgrade head
python -m app.bot.runner
```

API запускается в другом терминале:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Для периодических задач запустите worker и beat отдельно. Celery рассчитан на Linux; на Windows для воркеров используйте Docker или WSL.

```bash
celery -A app.scheduler.celery_app.celery_app worker -l info
celery -A app.scheduler.celery_app.celery_app beat -l info
```

## Сервер: webhook

Скопируйте `.env.server.example` в `.env`, заполните значения и задайте свой HTTPS-домен:

```dotenv
TELEGRAM_USE_POLLING=false
TELEGRAM_SET_WEBHOOK_ON_STARTUP=true
TELEGRAM_WEBHOOK_BASE=https://your-domain.example.com
PUBLIC_BASE_URL=https://your-domain.example.com
```

При обычном запуске Compose контейнерный Nginx слушает HTTP. HTTPS нужно обеспечить внешним reverse proxy. При Nginx на хосте используйте серверный override:

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

Этот override публикует API только на `127.0.0.1:8000` и исключает контейнер Nginx из обычного запуска. Пример `deploy/nginx/site.example.conf` предназначен для Nginx на хосте; замените домен и настройте TLS. Шаблон сам не создаёт сертификат.

В webhook-режиме polling runner завершается без обработки сообщений. Webhook Telegram проверяет заголовок `X-Telegram-Bot-Api-Secret-Token`.

## Оплата и VPN

Для ЮKassa заполните `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_RETURN_URL` и настройте событие `payment.succeeded` на `https://your-domain.example.com/api/v1/payments/yookassa/webhook`. Приложение получает актуальный платёж через авторизованный API и проверяет его до активации. `YOOKASSA_WEBHOOK_SECRET` — необязательная дополнительная проверка заголовка для собственного доверенного proxy; обычная ЮKassa не требует этого произвольного заголовка. [Документация ЮKassa](https://yookassa.ru/developers/using-api/webhooks).

Для Telegram Payments выберите `PAYMENT_PROVIDER=telegram` и укажите токен провайдера. Проверяйте оплату в тестовом режиме до рабочего запуска.

Панель 3x-ui должна быть настроена заранее. Команда `/addserver` сохраняет параметры существующего VLESS Reality inbound; бот не устанавливает VPN-сервер и не создаёт inbound автоматически.

## Диагностика

```bash
docker compose ps
docker compose logs --tail=100 migrate app bot worker beat
curl http://127.0.0.1/api/v1/health
```

HTTP health endpoint проверяет только ответ процесса. Для инфраструктуры смотрите health status контейнеров и логи. Сохраняйте резервные копии PostgreSQL и ключа шифрования отдельно от репозитория. `.env`, данные БД и Redis, логи и приватные ключи не включены в публикацию.
