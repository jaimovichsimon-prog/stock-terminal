import threading
import smtplib
import datetime
from email.mime.text import MIMEText
from config import NOTIFY_EMAIL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, APP_URL, logger


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


def _send_signup_email(new_user_email: str):
    msg = MIMEText(
        f"New user registered on Stock Terminal:\n\n"
        f"  Email: {new_user_email}\n"
        f"  Time:  {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n",
        "plain",
    )
    msg["Subject"] = f"[Stock Terminal] New sign-up: {new_user_email}"
    msg["From"]    = SMTP_USER
    msg["To"]      = NOTIFY_EMAIL
    _smtp_send(msg, NOTIFY_EMAIL)


def notify_new_user(email: str):
    threading.Thread(target=_send_signup_email, args=(email,), daemon=True).start()


def _send_reset_email(to_email: str, token: str):
    reset_url = f"{APP_URL}/?action=reset&token={token}"
    msg = MIMEText(
        f"Someone requested a password reset for your Terminal Pro account.\n\n"
        f"Click the link below to set a new password (valid for 1 hour):\n\n"
        f"{reset_url}\n\n"
        f"If you didn't request this, you can ignore this email.\n",
        "plain",
    )
    msg["Subject"] = "[Terminal Pro] Password Reset"
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    _smtp_send(msg, to_email)


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
