import threading
import time
import yfinance as yf
import psycopg

from config import SUPABASE_DB_URL, logger
from utils.market_data import clean_float


def _run_alert_checks():
    from services.email_service import send_alert_email

    if not SUPABASE_DB_URL:
        logger.warning("SUPABASE_DB_URL not set — skipping alert check")
        return

    try:
        with psycopg.connect(SUPABASE_DB_URL, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.id, a.ticker, a.condition, a.target_price, u.email
                    FROM public.price_alerts a
                    JOIN auth.users u ON u.id = a.user_id
                    WHERE a.triggered = FALSE
                """)
                alerts = cur.fetchall()  # list of (id, ticker, condition, target_price, email)

                if not alerts:
                    return

                tickers = list({a[1] for a in alerts})
                prices: dict = {}
                for tk in tickers:
                    try:
                        info = yf.Ticker(tk).info
                        p = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
                        if p:
                            prices[tk] = p
                    except Exception:
                        logger.warning("Alert price fetch failed for %s", tk, exc_info=True)

                triggered_count = 0
                for alert_id, ticker, condition, target_price, email in alerts:
                    price = prices.get(ticker)
                    if price is None:
                        continue
                    target = float(target_price)
                    hit = (
                        (condition == "above" and price >= target)
                        or (condition == "below" and price <= target)
                    )
                    if hit:
                        try:
                            cur.execute(
                                "UPDATE public.price_alerts SET triggered=TRUE, triggered_at=NOW() WHERE id=%s",
                                (alert_id,),
                            )
                            triggered_count += 1
                            threading.Thread(
                                target=send_alert_email,
                                args=(email, ticker, condition, target, price),
                                daemon=True,
                            ).start()
                        except Exception:
                            logger.warning("Failed to mark alert %s as triggered", alert_id, exc_info=True)

                conn.commit()
                logger.info(
                    "Alert check complete: %d alerts evaluated, %d prices fetched, %d triggered",
                    len(alerts), len(prices), triggered_count,
                )
    except Exception:
        logger.warning("Alert check loop error", exc_info=True)


def _alert_loop():
    while True:
        time.sleep(300)
        _run_alert_checks()


def start_alert_daemon():
    threading.Thread(target=_alert_loop, daemon=True).start()
    logger.info("Price alert daemon started")
