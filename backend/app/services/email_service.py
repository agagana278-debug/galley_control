"""SMTP email delivery service for password resets and security notifications.

Supports STARTTLS (ports 587/25), SSL/TLS direct (port 465), and unencrypted local relay.
Includes both plain-text and responsive HTML email templates with single-use reset links.
"""

from __future__ import annotations

import logging
import smtplib
import socket
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.config import settings

logger = logging.getLogger("galley_control.email")


def is_email_configured() -> bool:
    """Return True if an SMTP server host and sender address are configured."""
    return bool(settings.smtp_host and settings.smtp_from)


def _build_html_body(full_name: str, reset_url: str, ttl_minutes: int) -> str:
    """Construct a clean, professional HTML password reset email."""
    name_display = full_name.strip() if full_name else "Campus User"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Your Password — Galley Control</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
    .container {{ max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }}
    .header {{ background: linear-gradient(135deg, #4338ca 0%, #6366f1 100%); padding: 32px 28px; text-align: center; color: #ffffff; }}
    .header h1 {{ margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }}
    .header p {{ margin: 6px 0 0 0; font-size: 13px; opacity: 0.9; }}
    .content {{ padding: 32px 28px; font-size: 14px; line-height: 1.6; color: #334155; }}
    .greeting {{ font-size: 16px; font-weight: 700; color: #0f172a; margin-bottom: 12px; }}
    .btn-container {{ text-align: center; margin: 28px 0; }}
    .btn {{ display: inline-block; background-color: #4f46e5; color: #ffffff !important; font-weight: 700; font-size: 14px; padding: 14px 28px; text-decoration: none; border-radius: 12px; box-shadow: 0 4px 12px rgba(79, 70, 229, 0.25); }}
    .fallback {{ font-size: 12px; color: #64748b; background-color: #f8fafc; padding: 12px; border-radius: 8px; word-break: break-all; border: 1px solid #e2e8f0; margin-top: 20px; }}
    .notice {{ font-size: 12px; color: #64748b; margin-top: 24px; padding-top: 16px; border-top: 1px solid #f1f5f9; }}
    .footer {{ background-color: #f8fafc; padding: 20px 28px; text-align: center; font-size: 11px; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>GALLEY CONTROL</h1>
      <p>Campus Canteen Management Platform</p>
    </div>
    <div class="content">
      <div class="greeting">Hello {name_display},</div>
      <p>A password reset was requested for your Galley Control account. Click the button below to choose a new password:</p>
      
      <div class="btn-container">
        <a href="{reset_url}" class="btn" target="_blank" rel="noopener noreferrer">Reset Your Password</a>
      </div>

      <p>This password reset link is <strong>single-use</strong> and expires in <strong>{ttl_minutes} minutes</strong>.</p>
      
      <div class="fallback">
        If the button above does not work, copy and paste this link into your browser:<br>
        <a href="{reset_url}" style="color: #4f46e5;">{reset_url}</a>
      </div>

      <div class="notice">
        <strong>Did not request this change?</strong> You can safely ignore this email. Your current password will remain unchanged and your account is secure.
      </div>
    </div>
    <div class="footer">
      Protected by Galley Control multi-tenant authentication &bull; Automated security notification
    </div>
  </div>
</body>
</html>
"""


def _build_text_body(full_name: str, reset_url: str, ttl_minutes: int) -> str:
    """Construct plain text fallback version."""
    name_display = full_name.strip() if full_name else "Campus User"
    return (
        f"Hello {name_display},\n\n"
        "A password reset was requested for your Galley Control account.\n\n"
        f"Open the link below to set a new password:\n{reset_url}\n\n"
        f"Note: This link is single-use and expires in {ttl_minutes} minutes.\n\n"
        "If you did not request this, you can safely ignore this message. Your password will remain unchanged.\n\n"
        "— Galley Control Security Team"
    )


def send_password_reset_email(to_email: str, full_name: str, reset_url: str) -> dict:
    """Dispatch password reset email via configured SMTP transport.

    Returns dict with delivery status and mode details.
    """
    clean_to = (to_email or "").strip().lower()
    ttl = settings.password_reset_ttl_minutes

    if not is_email_configured():
        if settings.is_production:
            logger.warning(
                "Password reset requested for %s but SMTP_HOST is not configured in production.",
                clean_to,
            )
            return {"delivered": False, "mode": "smtp_unconfigured"}

        logger.info(
            "[DEV EMAIL FALLBACK] SMTP not configured. Password reset link for %s: %s",
            clean_to,
            reset_url,
        )
        return {"delivered": False, "mode": "dev_server_log"}

    msg = EmailMessage()
    msg["Subject"] = "Galley Control - Reset Your Password"
    msg["From"] = settings.smtp_from
    msg["To"] = clean_to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=settings.smtp_host or "galleycontrol.local")

    # Plain-text fallback
    msg.set_content(_build_text_body(full_name, reset_url, ttl))

    # Multipart HTML alternate
    msg.add_alternative(_build_html_body(full_name, reset_url, ttl), subtype="html")

    host = settings.smtp_host
    port = settings.smtp_port
    timeout = settings.smtp_timeout_seconds
    secure_mode = settings.smtp_secure

    # Determine SSL vs STARTTLS vs plain
    use_ssl = secure_mode == "ssl" or (secure_mode == "auto" and port == 465)
    use_starttls = secure_mode == "starttls" or (secure_mode == "auto" and port != 465 and port != 1025)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                if use_starttls:
                    server.starttls()
                    server.ehlo()
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)

        logger.info("Password reset email delivered successfully to %s via SMTP (%s:%d)", clean_to, host, port)
        return {"delivered": True, "mode": "smtp"}

    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP Authentication Error connecting to %s:%d: %s", host, port, exc)
        return {"delivered": False, "mode": "smtp_auth_error", "error": str(exc)}
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionRefusedError) as exc:
        logger.error("SMTP Connection Error connecting to %s:%d: %s", host, port, exc)
        return {"delivered": False, "mode": "smtp_connect_error", "error": str(exc)}
    except socket.timeout as exc:
        logger.error("SMTP Connection timed out connecting to %s:%d: %s", host, port, exc)
        return {"delivered": False, "mode": "smtp_timeout", "error": str(exc)}
    except smtplib.SMTPException as exc:
        logger.error("SMTP Protocol Error sending to %s via %s:%d: %s", clean_to, host, port, exc)
        return {"delivered": False, "mode": "smtp_error", "error": str(exc)}
    except Exception as exc:
        logger.exception("Unexpected error dispatching email to %s: %s", clean_to, exc)
        return {"delivered": False, "mode": "smtp_error", "error": str(exc)}
