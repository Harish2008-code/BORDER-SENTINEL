"""
Email verification module for passport screening.

When a passport is screened and the MySQL DB returns a gmail_id for
that passport holder, this module sends a verification email with a
unique token.  The screening result remains PENDING until the recipient
explicitly clicks APPROVE.  REJECT / EXPIRED / no-action all count as
*not approved*.
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

logger = logging.getLogger(__name__)

# Base URL for verification links (override via env var for production)
import os
BASE_URL = os.environ.get("BORDERSENTINEL_BASE_URL", "http://127.0.0.1:8000")


def _build_html_email(holder_name, doc_number, approve_url, reject_url, expiry_str):
    """Build a styled HTML email with button links."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0d1b2a;font-family:'Segoe UI',system-ui,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1b2a;padding:40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#1b2a3e;border-radius:16px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,0.3);">

  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#1a3a5c,#0f2744);padding:32px 40px;text-align:center;">
    <h1 style="margin:0;color:#4fc3f7;font-size:22px;font-weight:800;letter-spacing:2px;">
      BORDER<span style="color:#ffffff;">SENTINEL</span>
    </h1>
    <p style="margin:6px 0 0;color:#78909c;font-size:12px;letter-spacing:1px;">AI-Based Identity & Document Screening</p>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:36px 40px;">
    <h2 style="color:#e0e0e0;font-size:20px;margin:0 0 8px;">Identity Verification</h2>
    <p style="color:#90a4ae;font-size:14px;margin:0 0 24px;line-height:1.6;">
      Dear <strong style="color:#fff;">{holder_name or 'Passport Holder'}</strong>,
    </p>
    <p style="color:#90a4ae;font-size:14px;margin:0 0 12px;line-height:1.6;">
      A passport screening has been initiated for document
      <strong style="color:#4fc3f7;">{doc_number}</strong>.
      Your identity has been matched in our records.
    </p>
    <p style="color:#90a4ae;font-size:14px;margin:0 0 32px;line-height:1.6;">
      Please confirm your identity by clicking one of the buttons below:
    </p>

    <!-- Buttons -->
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:0 8px 0 0;">
        <a href="{approve_url}" target="_blank"
           style="display:inline-block;padding:16px 48px;background:#2e7d32;color:#ffffff;
                  text-decoration:none;border-radius:10px;font-size:16px;font-weight:700;
                  letter-spacing:1px;box-shadow:0 4px 16px rgba(46,125,50,0.4);
                  transition:background 0.2s;">
          ✅ APPROVE
        </a>
      </td>
      <td align="center" style="padding:0 0 0 8px;">
        <a href="{reject_url}" target="_blank"
           style="display:inline-block;padding:16px 48px;background:#c62828;color:#ffffff;
                  text-decoration:none;border-radius:10px;font-size:16px;font-weight:700;
                  letter-spacing:1px;box-shadow:0 4px 16px rgba(198,40,40,0.4);
                  transition:background 0.2s;">
          ❌ REJECT
        </a>
      </td>
    </tr>
    </table>

    <!-- Expiry notice -->
    <p style="color:#78909c;font-size:12px;margin:28px 0 0;text-align:center;line-height:1.5;">
      This verification expires at <strong style="color:#ffb74d;">{expiry_str}</strong>
    </p>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#0f1e30;padding:20px 40px;text-align:center;border-top:1px solid #263850;">
    <p style="color:#546e7a;font-size:11px;margin:0;line-height:1.5;">
      If you did not initiate this screening, click REJECT or ignore this email.<br>
      &mdash; BorderSentinel Automated Screening System
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def send_verification_email(screening_record, gmail_id: str,
                            holder_name: str = "",
                            doc_number: str = "",
                            base_url: str = "") -> "EmailVerification | None":
    from .models import EmailVerification

    token = secrets.token_urlsafe(48)
    expiry = timezone.now() + timedelta(
        seconds=settings.EMAIL_VERIFICATION_EXPIRY)

    ev = EmailVerification.objects.create(
        screening_record=screening_record,
        email=gmail_id,
        token=token,
        expires_at=expiry,
        status="PENDING",
    )

    # Prefer the public URL the app was accessed through (e.g. an ngrok
    # tunnel) so the buttons work from the recipient's email client.
    root = (base_url or BASE_URL).rstrip("/")
    approve_url = f"{root}/screen/email-verify/{token}/approve/"
    reject_url = f"{root}/screen/email-verify/{token}/reject/"
    expiry_str = expiry.strftime('%Y-%m-%d %H:%M UTC')

    subject = f"[BorderSentinel] Identity Verification — {doc_number}"

    # Plain-text fallback
    text_body = (
        f"Dear {holder_name or 'Passport Holder'},\n\n"
        f"A passport screening has been initiated for document {doc_number}.\n"
        f"Your identity has been matched in our records.\n\n"
        f"Please confirm your identity:\n\n"
        f"  APPROVE: {approve_url}\n"
        f"  REJECT:  {reject_url}\n\n"
        f"This link expires at {expiry_str}.\n\n"
        f"If you did not initiate this screening, click REJECT or ignore.\n\n"
        f"— BorderSentinel Automated Screening System\n"
    )

    html_body = _build_html_email(holder_name, doc_number,
                                  approve_url, reject_url, expiry_str)

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL or None,
            to=[gmail_id],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)

        ev.sent = True
        ev.save(update_fields=["sent"])
        logger.info("Verification email sent to %s for record #%s",
                     gmail_id, screening_record.pk)
    except Exception as exc:
        logger.exception("Failed to send verification email to %s: %s",
                         gmail_id, exc)
        ev.detail = f"Send failed: {exc}"
        ev.save(update_fields=["detail"])

    return ev


def check_verification_status(screening_record) -> dict:
    from .models import EmailVerification

    try:
        ev = EmailVerification.objects.filter(
            screening_record=screening_record
        ).latest("created_at")
    except EmailVerification.DoesNotExist:
        return {"status": "NOT_REQUIRED", "email": None,
                "detail": "No email verification required"}

    if ev.status == "PENDING" and timezone.now() > ev.expires_at:
        ev.status = "EXPIRED"
        ev.save(update_fields=["status"])

    return {
        "status": ev.status,
        "email": ev.email,
        "sent": ev.sent,
        "detail": ev.detail or f"Verification {ev.status.lower()}",
        "expires_at": ev.expires_at.isoformat() if ev.expires_at else None,
        "responded_at": ev.responded_at.isoformat() if ev.responded_at else None,
    }


def process_response(token: str, action: str) -> dict:
    from .models import EmailVerification

    try:
        ev = EmailVerification.objects.get(token=token)
    except EmailVerification.DoesNotExist:
        return {"success": False, "status": "INVALID",
                "detail": "Invalid or expired verification token"}

    if ev.status != "PENDING":
        return {"success": False, "status": ev.status,
                "detail": f"Verification already {ev.status.lower()}"}

    if timezone.now() > ev.expires_at:
        ev.status = "EXPIRED"
        ev.save(update_fields=["status"])
        return {"success": False, "status": "EXPIRED",
                "detail": "Verification token has expired"}

    if action == "approve":
        ev.status = "APPROVED"
    elif action == "reject":
        ev.status = "REJECTED"
    else:
        return {"success": False, "status": "INVALID",
                "detail": f"Unknown action: {action}"}

    ev.responded_at = timezone.now()
    ev.save(update_fields=["status", "responded_at"])

    ev.screening_record.append_audit(
        f"email_{action}d",
        f"Email verification {action}d by {ev.email}"
    )

    return {"success": True, "status": ev.status,
            "detail": f"Verification {action}d successfully"}


# ---------------------------------------------------------------------------
# General information email (informational only - no approve/reject flow)
# ---------------------------------------------------------------------------

# Authority contact details shown to the holder for reaching the screening desk
AUTHORITY_NAME = os.environ.get("BS_AUTHORITY_NAME", "BorderSentinel Screening Desk")
AUTHORITY_EMAIL = os.environ.get("BS_AUTHORITY_EMAIL",
                                 settings.DEFAULT_FROM_EMAIL or "")
AUTHORITY_PHONE = os.environ.get("BS_AUTHORITY_PHONE", "+91-1800-000-000")


def send_info_email(gmail_id, holder_name="", doc_number="",
                    doc_type="", risk_level="", record=None):
    """Send a plain informational notice to the document holder.

    This is NOT a verification request - it simply informs the holder that
    their document was screened and gives them contact details for the
    screening authority in case they need to get in touch.
    Returns True on success, False on failure.
    """
    subject = f"BorderSentinel - Identity Screening Notification ({doc_number})"

    text_body = (
        f"Dear {holder_name or 'Traveller'},\n\n"
        f"This is an informational notice from {AUTHORITY_NAME}.\n\n"
        f"Your identity document ({doc_type or 'document'} {doc_number}) "
        f"has been processed by our automated screening system.\n"
        f"Reference: Screening #{getattr(record, 'pk', '-')}\n\n"
        f"No action is required from you at this time. This message is sent "
        f"for your information only.\n\n"
        f"If you have any questions or need to contact us, please reach out:\n"
        f"  Email : {AUTHORITY_EMAIL}\n"
        f"  Phone : {AUTHORITY_PHONE}\n\n"
        f"Regards,\n"
        f"{AUTHORITY_NAME}\n"
    )

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:#f4f6f8;font-family:'Segoe UI',system-ui,Arial,sans-serif;color:#2b3b55;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e0e4ea;border-radius:10px;padding:28px 32px;">
    <h2 style="margin:0 0 4px;color:#1a3a5c;font-size:18px;">BorderSentinel</h2>
    <p style="margin:0 0 20px;color:#78909c;font-size:12px;">Identity Screening Notification</p>

    <p style="font-size:14px;">Dear <strong>{holder_name or 'Traveller'}</strong>,</p>
    <p style="font-size:14px;line-height:1.6;">
      This is an informational notice from {AUTHORITY_NAME}. Your identity document
      (<strong>{doc_type or 'document'} {doc_number}</strong>) has been processed by our
      automated screening system.
    </p>
    <p style="font-size:14px;line-height:1.6;">
      Reference: <strong>Screening #{getattr(record, 'pk', '-')}</strong><br>
      No action is required from you at this time.
    </p>

    <div style="margin:20px 0;padding:16px 18px;background:#f4f8fb;border-radius:8px;border:1px solid #e0e8f0;">
      <p style="margin:0 0 8px;font-weight:600;font-size:13px;color:#1a3a5c;">Contact us</p>
      <p style="margin:0;font-size:13px;line-height:1.7;">
        Email: <a href="mailto:{AUTHORITY_EMAIL}" style="color:#1a73e8;">{AUTHORITY_EMAIL}</a><br>
        Phone: <a href="tel:{AUTHORITY_PHONE}" style="color:#1a73e8;">{AUTHORITY_PHONE}</a>
      </p>
    </div>

    <p style="font-size:12px;color:#90a4ae;margin:16px 0 0;">
      This message was sent for your information only. If you did not travel or
      believe this was sent in error, please contact us at the details above.
    </p>
    <p style="font-size:12px;color:#90a4ae;margin:12px 0 0;">Regards,<br>{AUTHORITY_NAME}</p>
  </div>
</body></html>"""

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL or None,
            to=[gmail_id],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        logger.info("Info email sent to %s (record #%s)",
                     gmail_id, getattr(record, "pk", "-"))
        return True
    except Exception as exc:
        logger.exception("Failed to send info email to %s: %s", gmail_id, exc)
        return False
