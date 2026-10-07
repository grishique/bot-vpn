"""Business and integration contract tests using only synthetic configuration."""

import os
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

# Explicit settings keep developer credentials out of the test process.
from app.config.settings import Settings

TEST_SETTINGS = Settings(
    _env_file=None,
    APP_SECRET_KEY="unit-tests-only-do-not-use-in-production",
    DATABASE_URL="postgresql+asyncpg://test:test@127.0.0.1/test",
    SYNC_DATABASE_URL="postgresql+psycopg://test:test@127.0.0.1/test",
    REDIS_URL="redis://127.0.0.1:6379/0",
    CELERY_BROKER_URL="redis://127.0.0.1:6379/0",
    CELERY_RESULT_BACKEND="redis://127.0.0.1:6379/1",
    TELEGRAM_BOT_TOKEN="1234567890:test-token",
    TELEGRAM_PROVIDER_TOKEN="",
    TELEGRAM_WEBHOOK_BASE="https://example.com",
    TELEGRAM_WEBHOOK_PATH="/webhook/telegram",
    TELEGRAM_WEBHOOK_SECRET="test-webhook-secret",
)
os.environ.update({
    field.alias: str(getattr(TEST_SETTINGS, name))
    for name, field in Settings.model_fields.items()
    if field.alias and getattr(TEST_SETTINGS, name) is not None
})

from app.services.payment_service import payment_service
from app.services.promocode_service import promocode_service
from app.services.xui_service import ThreeXUIService, XUIError
from app.services.yookassa_service import YooKassaPayment, YooKassaService
from app.utils import security
from app.utils.qr import build_qr_code
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routers import payments as payments_api
from app.models.enums import PaymentProvider, PaymentStatus


class PricingTests(unittest.TestCase):
    def test_minor_units_round_half_up(self):
        for value, expected in [("0.01", 1), ("19.995", 2000), ("100.00", 10000)]:
            with self.subTest(value=value):
                self.assertEqual(payment_service.to_minor_units(Decimal(value)), expected)

    def test_fixed_discount_is_capped_at_plan_price(self):
        plan = SimpleNamespace(price_amount=Decimal("100.00"))
        promo = SimpleNamespace(discount_amount=Decimal("150.00"), discount_percent=None)
        self.assertEqual(promocode_service.calculate_discount(plan, promo), Decimal("100.00"))

    def test_percentage_discount_and_bonus_days(self):
        plan = SimpleNamespace(price_amount=Decimal("250.00"))
        promo = SimpleNamespace(discount_amount=None, discount_percent=15, bonus_days=7)
        charge = payment_service.get_plan_charge(plan, promo)
        self.assertEqual(charge.final_amount, Decimal("212.50"))
        self.assertEqual(charge.discount_amount, Decimal("37.50"))
        self.assertEqual(charge.promo_bonus_days, 7)

    def test_full_discount_keeps_minimum_invoice_amount(self):
        plan = SimpleNamespace(price_amount=Decimal("100.00"))
        promo = SimpleNamespace(discount_amount=Decimal("100.00"), discount_percent=None, bonus_days=0)
        self.assertEqual(payment_service.get_plan_charge(plan, promo).final_amount, Decimal("0.01"))

    def test_negative_bonus_days_do_not_reduce_subscription(self):
        self.assertEqual(promocode_service.get_bonus_days(SimpleNamespace(bonus_days=-3)), 0)


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.settings_patch = patch.object(security, 'get_settings', return_value=TEST_SETTINGS)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_encryption_roundtrip_for_unicode(self):
        original = "тестовый пароль"
        ciphertext = security.encrypt_text(original)
        self.assertNotIn(original, ciphertext)
        self.assertEqual(security.decrypt_text(ciphertext), original)

    def test_subscription_token_roundtrip(self):
        subscription_id = str(uuid4())
        token = security.generate_subscription_token(subscription_id)
        self.assertEqual(security.parse_subscription_token(token), subscription_id)

    def test_tampered_subscription_token_is_rejected(self):
        token = security.generate_subscription_token(str(uuid4()))
        with self.assertRaises(ValueError):
            security.parse_subscription_token('!' + token[1:])

    def test_encrypted_payload_with_wrong_purpose_is_rejected(self):
        with self.assertRaises(ValueError):
            security.parse_subscription_token(security.encrypt_text('invoice:123'))

    def test_qr_is_a_png_in_memory(self):
        with patch('app.utils.qr.get_settings', return_value=TEST_SETTINGS):
            result = build_qr_code('vless://test@example.com:443')
        self.assertIsInstance(result, BytesIO)
        self.assertEqual(result.read(8), b'\x89PNG\r\n\x1a\n')


class VlessTests(unittest.TestCase):
    def setUp(self):
        self.service = ThreeXUIService()
        self.server = SimpleNamespace(
            name='Test & Server', host='vpn.example.com', port=443,
            flow='xtls-rprx-vision', sni='example.com', fingerprint='chrome',
            public_key='test+public/key', short_id='abcd', spider_x='/', transport='tcp',
        )
        self.subscription = SimpleNamespace(
            id=uuid4(), vless_uuid=str(uuid4()), client_email='synthetic-client',
            xui_client_id=None, plan=SimpleNamespace(traffic_limit_gb=5),
        )

    def test_vless_url_preserves_encoded_parameters(self):
        url = urlsplit(self.service.build_vless_url(self.server, self.subscription))
        self.assertEqual(url.scheme, 'vless')
        self.assertEqual(url.hostname, self.server.host)
        self.assertEqual(url.port, 443)
        params = parse_qs(url.query)
        self.assertEqual(params['pbk'], [self.server.public_key])
        self.assertEqual(params['security'], ['reality'])
        self.assertEqual(params['spx'], ['/'])

    def test_client_payload_sets_byte_quota_and_expiration(self):
        expiration = datetime(2027, 1, 1, tzinfo=timezone.utc)
        payload = self.service._build_client_payload(self.server, self.subscription, expiration)
        self.assertEqual(payload['totalGB'], 5 * 1024**3)
        self.assertEqual(payload['expiryTime'], int(expiration.timestamp() * 1000))
        self.assertEqual(payload['id'], self.subscription.vless_uuid)

    def test_panel_rejection_becomes_domain_error(self):
        response = httpx.Response(200, json={'success': False, 'msg': 'rejected'})
        with self.assertRaises(XUIError):
            self.service._ensure_success(response, 'addClient')


class YooKassaTests(unittest.TestCase):
    def setUp(self):
        self.service = YooKassaService()
        self.remote = YooKassaPayment(
            payment_id='provider-1', confirmation_url='', status='succeeded',
            amount=Decimal('100.00'), currency='RUB', invoice_payload='invoice-1',
        )
        self.local = SimpleNamespace(
            amount_total=Decimal('100.00'), currency='RUB',
            invoice_payload='invoice-1', provider_payment_id='provider-1',
        )

    def test_verified_provider_payment_matches_local_invoice(self):
        self.assertTrue(self.service.matches_payment(self.remote, self.local))

    def test_mismatched_status_amount_currency_or_invoice_is_rejected(self):
        changes = [dict(status='pending'), dict(amount=Decimal('1.00')),
                   dict(currency='USD'), dict(invoice_payload='other'), dict(payment_id='other')]
        for change in changes:
            with self.subTest(change=change):
                self.assertFalse(self.service.matches_payment(replace(self.remote, **change), self.local))

    def test_optional_proxy_secret_validation(self):
        settings = TEST_SETTINGS.model_copy(update={'yookassa_webhook_secret': 'proxy-secret'})
        with patch('app.services.yookassa_service.get_settings', return_value=settings):
            self.assertTrue(self.service.is_valid_webhook('proxy-secret'))
            self.assertFalse(self.service.is_valid_webhook(None))
            self.assertFalse(self.service.is_valid_webhook('wrong'))


class YooKassaWebhookTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(payments_api.router)
        app.state.bot = SimpleNamespace(send_message=AsyncMock())
        self.client = TestClient(app)
        self.session = AsyncMock()
        self.context = AsyncMock()
        self.context.__aenter__.return_value = self.session
        self.local = SimpleNamespace(
            status=PaymentStatus.PENDING, provider=PaymentProvider.YOOKASSA,
            amount_total=Decimal('100.00'), currency='RUB', invoice_payload='invoice-1',
            provider_payment_id='provider-1', user=SimpleNamespace(telegram_id=1),
        )
        self.remote = YooKassaPayment(
            payment_id='provider-1', confirmation_url='', status='succeeded',
            amount=Decimal('100.00'), currency='RUB', invoice_payload='invoice-1',
        )
        mocks = [
            patch.object(payments_api, 'AsyncSessionFactory', return_value=self.context),
            patch.object(payments_api.yookassa_service, 'is_valid_webhook', return_value=True),
            patch.object(payments_api.yookassa_service, 'get_payment', AsyncMock(return_value=self.remote)),
            patch.object(payments_api.payment_service, 'get_by_provider_payment_id', AsyncMock(return_value=self.local)),
            patch.object(payments_api.payment_service, 'get_by_payload', AsyncMock(return_value=self.local)),
            patch.object(payments_api.payment_service, 'mark_paid_and_activate', AsyncMock(return_value=SimpleNamespace(
                balance_topup_amount=None, wallet_balance=None, codex_pass_reward=None, subscription=None,
            ))),
        ]
        for mocked in mocks:
            mocked.start()
            self.addCleanup(mocked.stop)

    def notify(self):
        return self.client.post('/payments/yookassa/webhook', json={
            'event': 'payment.succeeded',
            'object': {'id': 'provider-1', 'metadata': {'invoice_payload': 'untrusted-invoice'}},
        })

    def test_pending_provider_status_does_not_activate(self):
        payments_api.yookassa_service.get_payment.return_value = replace(self.remote, status='pending')
        self.assertEqual(self.notify().status_code, 400)
        payments_api.payment_service.mark_paid_and_activate.assert_not_awaited()
        self.session.commit.assert_not_awaited()

    def test_confirmed_matching_payment_activates(self):
        self.assertEqual(self.notify().status_code, 200)
        payments_api.payment_service.mark_paid_and_activate.assert_awaited_once()
        self.session.commit.assert_awaited_once()

    def test_already_paid_notification_does_not_activate_again(self):
        self.local.status = PaymentStatus.PAID
        self.assertEqual(self.notify().status_code, 200)
        payments_api.payment_service.mark_paid_and_activate.assert_not_awaited()

    def test_invoice_fallback_uses_provider_metadata(self):
        payments_api.payment_service.get_by_provider_payment_id.return_value = None
        self.local.provider_payment_id = None
        self.assertEqual(self.notify().status_code, 200)
        payments_api.payment_service.get_by_payload.assert_awaited_once_with(self.session, 'invoice-1')


if __name__ == '__main__':
    unittest.main()
