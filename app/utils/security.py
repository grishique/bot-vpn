"""Helpers for token generation and field encryption."""

from __future__ import annotations

import base64
import hashlib
import secrets
from uuid import uuid4

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken

from app.config.settings import get_settings


def _build_fernet() -> Fernet:
    """Build a Fernet instance derived from the app secret."""
    settings = get_settings()
    digest = hashlib.sha256(settings.app_secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_text(value: str) -> str:
    """Encrypt a string for storage."""
    return _build_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_text(value: str) -> str:
    """Decrypt a previously encrypted string."""
    return _build_fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def generate_referral_code() -> str:
    """Generate a compact referral code."""
    return secrets.token_urlsafe(6).upper().replace("-", "").replace("_", "")


def generate_invoice_payload() -> str:
    """Generate a unique invoice payload."""
    return f"vpn:{uuid4().hex}"


def generate_client_uuid() -> str:
    """Generate a client UUID for VLESS."""
    return str(uuid4())


def generate_subscription_token(subscription_id: str) -> str:
    """Generate an opaque token for a public subscription URL."""
    return encrypt_text(f"subscription:{subscription_id}")


def parse_subscription_token(token: str) -> str:
    """Decode a public subscription token back to a subscription id."""
    try:
        payload = decrypt_text(token)
    except InvalidToken as exc:
        raise ValueError("Invalid subscription token.") from exc

    prefix = "subscription:"
    if not payload.startswith(prefix):
        raise ValueError("Invalid subscription token.")
    return payload.removeprefix(prefix)
