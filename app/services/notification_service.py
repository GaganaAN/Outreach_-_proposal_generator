"""
Notification Service — sends in-app + email alerts to the marketing team
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Notification, Opportunity

logger = logging.getLogger(__name__)


class NotificationService:
    """Creates in-app notifications and optionally sends email alerts."""

    def __init__(self):
        self.settings = get_settings()

    def notify_opportunity(
        self,
        opportunity: Opportunity,
        signal_result,   # SignalResult dataclass
        db: Session,
    ) -> Optional[Notification]:
        """
        Create in-app notification and send email alert for a proposal opportunity.

        Args:
            opportunity:   The Opportunity DB record
            signal_result: The SignalResult from the classifier
            db:            Active DB session

        Returns:
            Created Notification record, or None on failure
        """
        try:
            skills_str = ", ".join(signal_result.detected_skills[:5]) or "N/A"
            company = opportunity.company_name or "Unknown Company"
            sig_type_label = signal_result.signal_type.replace("_", " ").title()

            title = f"New {sig_type_label}: {company}"
            message = (
                f"A {sig_type_label} signal was detected.\n\n"
                f"Company: {company}\n"
                f"Source: {signal_result.source_url or 'Manual input'}\n"
                f"Detected Skills: {skills_str}\n"
                f"Confidence: {signal_result.confidence_score:.0%}\n"
                f"Priority: {opportunity.priority.upper()}\n"
                f"Score: {opportunity.overall_score:.2f}\n\n"
                f"Recommended Action: Contact the company and request the RFP document."
            )

            email_sent = False
            if self.settings.MARKETING_EMAIL and self.settings.SMTP_HOST:
                email_sent = self._send_email(title, message, company, skills_str, opportunity)

            notification = Notification(
                opportunity_id=opportunity.id,
                title=title,
                message=message,
                is_read=False,
                email_sent=email_sent,
            )
            db.add(notification)
            db.commit()
            db.refresh(notification)

            logger.info(f"Notification created (id={notification.id}, email_sent={email_sent})")
            return notification

        except Exception as e:
            logger.error(f"Failed to create notification: {e}")
            return None

    def _send_email(
        self,
        subject: str,
        plain_body: str,
        company: str,
        skills_str: str,
        opportunity: Opportunity,
    ) -> bool:
        """Send HTML email alert via SMTP."""
        try:
            html_body = f"""
<html><body style="font-family:Arial,sans-serif;color:#222;">
<h2 style="color:#d4741e;">🚨 New Opportunity Alert</h2>
<table style="border-collapse:collapse;width:100%;max-width:600px;">
  <tr><td style="padding:8px;font-weight:bold;">Company</td><td style="padding:8px;">{company}</td></tr>
  <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Signal Type</td>
      <td style="padding:8px;">{opportunity.opportunity_type.replace('_',' ').title()}</td></tr>
  <tr><td style="padding:8px;font-weight:bold;">Detected Skills</td><td style="padding:8px;">{skills_str}</td></tr>
  <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Priority</td>
      <td style="padding:8px;"><strong>{opportunity.priority.upper()}</strong></td></tr>
  <tr><td style="padding:8px;font-weight:bold;">Score</td><td style="padding:8px;">{opportunity.overall_score:.2f} / 1.00</td></tr>
  <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Source</td>
      <td style="padding:8px;">{opportunity.source_url or 'Manual input'}</td></tr>
</table>
<br>
<p style="background:#fff3cd;padding:12px;border-left:4px solid #d4741e;">
  <strong>Recommended Action:</strong> Contact the company and request the RFP document.
  Then upload it in the <a href="{self.settings.COMPANY_WEBSITE}">Outreach Platform</a>
  to auto-generate a proposal.
</p>
</body></html>
"""
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[Opportunity Alert] {subject}"
            msg["From"] = self.settings.SMTP_FROM_EMAIL or self.settings.SMTP_USERNAME
            msg["To"] = self.settings.MARKETING_EMAIL
            msg.attach(MIMEText(plain_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(self.settings.SMTP_HOST, self.settings.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if self.settings.SMTP_USERNAME and self.settings.SMTP_PASSWORD:
                    server.login(self.settings.SMTP_USERNAME, self.settings.SMTP_PASSWORD)
                server.sendmail(msg["From"], [self.settings.MARKETING_EMAIL], msg.as_string())

            logger.info(f"Alert email sent to {self.settings.MARKETING_EMAIL}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(
                f"SMTP authentication failed — Gmail requires an App Password, not your account "
                f"password. Generate one at myaccount.google.com → Security → App Passwords. Error: {e}"
            )
            return False
        except smtplib.SMTPConnectError as e:
            logger.error(f"Cannot connect to SMTP server {self.settings.SMTP_HOST}:{self.settings.SMTP_PORT} — {e}")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending alert email: {e}")
            return False
        except Exception as e:
            logger.warning(f"Email alert failed (non-critical): {e}")
            return False

    def test_email(self) -> dict:
        """Send a test email to MARKETING_EMAIL to verify SMTP config. Returns status dict."""
        if not self.settings.SMTP_HOST:
            return {"success": False, "error": "SMTP_HOST is not configured in .env"}
        if not self.settings.MARKETING_EMAIL:
            return {"success": False, "error": "MARKETING_EMAIL is not configured in .env"}

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "[Mailposalix] SMTP Test Email"
            msg["From"] = self.settings.SMTP_FROM_EMAIL or self.settings.SMTP_USERNAME
            msg["To"] = self.settings.MARKETING_EMAIL
            body = (
                "This is a test email from Mailposalix.\n\n"
                "If you received this, your SMTP configuration is working correctly.\n\n"
                f"From: {self.settings.SMTP_FROM_EMAIL or self.settings.SMTP_USERNAME}\n"
                f"To: {self.settings.MARKETING_EMAIL}\n"
                f"Host: {self.settings.SMTP_HOST}:{self.settings.SMTP_PORT}"
            )
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.settings.SMTP_HOST, self.settings.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if self.settings.SMTP_USERNAME and self.settings.SMTP_PASSWORD:
                    server.login(self.settings.SMTP_USERNAME, self.settings.SMTP_PASSWORD)
                server.sendmail(msg["From"], [self.settings.MARKETING_EMAIL], msg.as_string())

            logger.info(f"Test email sent successfully to {self.settings.MARKETING_EMAIL}")
            return {"success": True, "message": f"Test email sent to {self.settings.MARKETING_EMAIL}"}

        except smtplib.SMTPAuthenticationError:
            return {
                "success": False,
                "error": (
                    "Authentication failed. Gmail requires an App Password — not your regular account password. "
                    "Go to myaccount.google.com → Security → 2-Step Verification → App Passwords, "
                    "create one and paste it as SMTP_PASSWORD in .env"
                ),
            }
        except smtplib.SMTPConnectError as e:
            return {
                "success": False,
                "error": f"Cannot connect to {self.settings.SMTP_HOST}:{self.settings.SMTP_PORT} — {e}",
            }
        except smtplib.SMTPException as e:
            return {"success": False, "error": f"SMTP error: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_notification_service = None


def get_notification_service() -> NotificationService:
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
