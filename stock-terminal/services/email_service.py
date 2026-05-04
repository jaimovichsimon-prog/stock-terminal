import smtplib
import datetime
from email.mime.text import MIMEText

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, logger


def _smtp_send(msg: MIMEText, to: str):
    """Send a single email via SMTP. Skips silently if SMTP is not configured."""
    if not SMTP_USER or not SMTP_PASSWORD:
        return
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, [to], msg.as_string())
    except Exception:
        logger.warning("SMTP send failed", exc_info=True)


def send_alert_email(to_email: str, ticker: str, condition: str, target: float, current: float):
    direction = "above" if condition == "above" else "below"
    msg = MIMEText(
        f"Price alert triggered for {ticker}:\n\n"
        f"  Your alert:    price {direction} ${target:,.2f}\n"
        f"  Current price: ${current:,.2f}\n"
        f"  Time: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
        f"Log in to Terminal Pro to view your positions.\n",
        "plain",
    )
    msg["Subject"] = f"[Terminal Pro] Alert: {ticker} is {direction} ${target:,.2f}"
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    _smtp_send(msg, to_email)
