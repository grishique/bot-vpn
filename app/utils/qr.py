"""QR-code generation utilities."""

from __future__ import annotations

from io import BytesIO

import qrcode

from app.config.settings import get_settings


def build_qr_code(data: str) -> BytesIO:
    """Generate an in-memory QR code image."""
    settings = get_settings()
    qr = qrcode.QRCode(
        version=1,
        box_size=settings.qr_box_size,
        border=settings.qr_border,
    )
    qr.add_data(data)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
