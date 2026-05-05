"""
Sends the HTML email via Gmail SMTP.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from config import TZ, REPORT_LANGUAGE

log = logging.getLogger(__name__)

def send_email(html_content: str, watchlist: list[str]) -> bool:
    """Send the report email via Gmail SMTP. Returns True on success."""
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("RECIPIENT_EMAIL")

    if not all([sender, password, recipient]):
        log.error("❌ Email env vars not set: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL")
        return False

    now = datetime.now(TZ).strftime("%m/%d")

    if REPORT_LANGUAGE == "ko":
        subject = f"📈 일일 주식 분석 리포트 ({now}) — {', '.join(watchlist)}"
    else:
        subject = f"📈 Daily Stock Report ({now}) — {', '.join(watchlist)}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        log.info(f"Email sent → {recipient}")
        return True
    except Exception as e:
        log.error(f"Email send failed: {e}")
        return False