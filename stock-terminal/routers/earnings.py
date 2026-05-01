import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd
import yfinance as yf

from fastapi import APIRouter

from config import logger
from utils.market_data import clean_float, deep_clean
from services.cache import earnings_cache

router = APIRouter()

_EARNINGS_WATCH = [
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AVGO","JPM","V",
    "UNH","JNJ","XOM","WMT","MA","PG","HD","CVX","BAC","ABBV","LLY","MRK",
    "COST","KO","PEP","MCD","TMO","CRM","ACN","AMD","TXN","ORCL","CSCO",
    "QCOM","INTC","IBM","NOW","ADBE","INTU","GS","MS","BLK","RTX","CAT",
    "DE","HON","UPS","BA","GE","LMT","AMGN","GILD","REGN","VRTX","BMY",
    "PFE","MRNA","ISRG","MDT","ABT","NFLX","DIS","CMCSA","T","VZ","NEE",
    "NEM","FCX","LIN","APD","SHW","F","GM","RIVN","PLTR","SNOW","COIN",
]


@router.get("/earnings")
def get_earnings(tickers: str = ""):
    if not tickers.strip():
        return {"earnings": []}

    syms    = [t.strip().upper() for t in tickers.split(",") if t.strip()][:20]
    results = []
    today   = datetime.date.today()

    for sym in syms:
        try:
            t       = yf.Ticker(sym)
            info    = t.info
            company = info.get("longName") or info.get("shortName") or sym

            try:
                ed = t.earnings_dates
                if ed is not None and not ed.empty:
                    future = ed[ed.index >= pd.Timestamp(today, tz="America/New_York")]
                    if not future.empty:
                        row = future.iloc[-1]
                        results.append({
                            "ticker":        sym,
                            "company_name":  company,
                            "earnings_date": future.index[-1].strftime("%Y-%m-%d"),
                            "eps_estimate":  clean_float(row.get("EPS Estimate")),
                            "eps_actual":    clean_float(row.get("Reported EPS")),
                            "surprise_pct":  None,
                        })
                        continue
            except Exception:
                logger.warning("earnings_dates failed for %s", sym, exc_info=True)

            cal = t.calendar
            if cal and isinstance(cal, dict):
                dates = cal.get("Earnings Date", [])
                if isinstance(dates, list) and dates:
                    edate = dates[0]
                elif hasattr(dates, "date"):
                    edate = dates
                else:
                    edate = None
                if edate:
                    if hasattr(edate, "date"):
                        edate = edate.date()
                    results.append({
                        "ticker":        sym,
                        "company_name":  company,
                        "earnings_date": str(edate),
                        "eps_estimate":  clean_float(cal.get("EPS Estimate")),
                        "eps_actual":    None,
                        "surprise_pct":  None,
                    })
        except Exception:
            logger.warning("Earnings fetch failed for %s", sym, exc_info=True)

    results.sort(key=lambda x: x.get("earnings_date") or "9999-99-99")
    return deep_clean({"earnings": results})


def _fetch_one_earnings(sym: str) -> Optional[dict]:
    try:
        today   = datetime.date.today()
        cutoff  = today + datetime.timedelta(days=60)
        tk      = yf.Ticker(sym)
        info    = tk.info
        company = info.get("longName") or info.get("shortName") or sym
        try:
            ed = tk.earnings_dates
            if ed is not None and not ed.empty:
                future = ed[ed.index >= pd.Timestamp(today, tz="America/New_York")]
                if not future.empty:
                    row   = future.iloc[-1]
                    edate = future.index[-1].date()
                    if edate <= cutoff:
                        return {
                            "ticker":         sym,
                            "company_name":   company,
                            "sector":         info.get("sector", ""),
                            "earnings_date":  str(edate),
                            "eps_estimate":   clean_float(row.get("EPS Estimate")),
                            "market_cap":     clean_float(info.get("marketCap")),
                        }
        except Exception:
            logger.warning("earnings_dates failed for %s in upcoming", sym, exc_info=True)

        cal = tk.calendar
        if cal and isinstance(cal, dict):
            dates = cal.get("Earnings Date", [])
            edate = dates[0] if isinstance(dates, list) and dates else dates
            if hasattr(edate, "date"):
                edate = edate.date()
            if edate and isinstance(edate, datetime.date) and edate <= cutoff:
                return {
                    "ticker":        sym,
                    "company_name":  company,
                    "sector":        info.get("sector", ""),
                    "earnings_date": str(edate),
                    "eps_estimate":  clean_float(cal.get("EPS Estimate")),
                    "market_cap":    clean_float(info.get("marketCap")),
                }
    except Exception:
        logger.warning("Upcoming earnings fetch failed for %s", sym, exc_info=True)
    return None


@router.get("/earnings/upcoming")
def get_upcoming_earnings():
    cached = earnings_cache.get("main")
    if cached is not None:
        return cached

    results = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_fetch_one_earnings, sym): sym for sym in _EARNINGS_WATCH}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: x.get("earnings_date") or "9999")
    result = deep_clean({"earnings": results, "fetched_at": datetime.datetime.utcnow().isoformat()})
    earnings_cache.set("main", result)
    return result
