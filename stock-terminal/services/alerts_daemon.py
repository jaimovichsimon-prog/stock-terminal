import threading
import time
import yfinance as yf
from sqlalchemy.orm import Session
from sqlalchemy import select
from config import logger
from database import SessionLocal
from utils.market_data import clean_float


def _run_alert_checks():
    from models import PriceAlert, User
    from services.email_service import send_alert_email

    db: Session = SessionLocal()
    try:
        alerts = db.execute(select(PriceAlert).where(PriceAlert.triggered == 0)).scalars().all()
        if not alerts:
            return

        tickers = list({a.ticker for a in alerts})
        prices: dict = {}
        for tk in tickers:
            try:
                info = yf.Ticker(tk).info
                p = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
                if p:
                    prices[tk] = p
            except Exception:
                logger.warning("Alert price fetch failed for %s", tk, exc_info=True)

        for alert in alerts:
            price = prices.get(alert.ticker)
            if price is None:
                continue
            hit = (
                (alert.condition == "above" and price >= alert.target_price)
                or (alert.condition == "below" and price <= alert.target_price)
            )
            if hit:
                alert.triggered = 1
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.warning("Failed to mark alert %s as triggered", alert.id, exc_info=True)
                    continue
                user = db.execute(select(User).where(User.id == alert.user_id)).scalar_one_or_none()
                if user:
                    threading.Thread(
                        target=send_alert_email,
                        args=(user.email, alert.ticker, alert.condition, alert.target_price, price),
                        daemon=True,
                    ).start()
        logger.info("Alert check complete: %d alerts evaluated, %d prices fetched", len(alerts), len(prices))
    except Exception:
        logger.warning("Alert check loop error", exc_info=True)
    finally:
        db.close()


def _alert_loop():
    while True:
        time.sleep(300)
        _run_alert_checks()


def start_alert_daemon():
    threading.Thread(target=_alert_loop, daemon=True).start()
    logger.info("Price alert daemon started")
