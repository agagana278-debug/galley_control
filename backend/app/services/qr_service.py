"""Unique QR token and PNG image generation using Python qrcode."""

import base64
import io
import secrets
import qrcode


def generate_qr_token(order_code: str) -> str:
    """Create a unique single-use pickup token bound to an order code."""
    nonce = secrets.token_hex(4).upper()
    return f"GC-{order_code}-{nonce}"


def render_qr_base64(token: str) -> str:
    """Generate a base64-encoded PNG data URI for a QR pickup token."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(token)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0E1B3D", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
