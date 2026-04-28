from pathlib import Path
import math
import datetime
import os
import json
import time
import re
from typing import List

import numpy as np
import pandas as pd
import yfinance as yf
import feedparser
import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Stock Terminal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INDEX_HTML = Path(__file__).parent / "index.html"


@app.get("/")
def index():
    return FileResponse(str(INDEX_HTML))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_float(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def deep_clean(obj):
    if isinstance(obj, dict):
        return {k: deep_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_clean(v) for v in obj]
    if isinstance(obj, float):
        return clean_float(obj)
    try:
        f = float(obj)
        if math.isnan(f) or math.isinf(f):
            return None
    except (TypeError, ValueError):
        pass
    return obj


def safe_last(series: pd.Series):
    if series is None or series.empty:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def chart_col(series: pd.Series):
    return [None if pd.isna(v) else round(float(v), 4) for v in series]


# ---------------------------------------------------------------------------
# Technical indicator calculations (no pandas_ta dependency)
# ---------------------------------------------------------------------------

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period, min_periods=period).mean()


def compute_consensus(rec_df):
    empty = {"buy": None, "hold": None, "sell": None, "consensus": None}
    if rec_df is None or (hasattr(rec_df, "empty") and rec_df.empty):
        return empty
    required = {"strongBuy", "buy", "hold", "sell", "strongSell"}
    if not required.issubset(set(rec_df.columns)):
        return empty
    row = rec_df.iloc[0]
    strong_buy  = int(row.get("strongBuy",  0) or 0)
    buy         = int(row.get("buy",        0) or 0)
    hold        = int(row.get("hold",       0) or 0)
    sell        = int(row.get("sell",       0) or 0)
    strong_sell = int(row.get("strongSell", 0) or 0)
    total = strong_buy + buy + hold + sell + strong_sell
    if total == 0:
        return empty
    total_buy  = strong_buy + buy
    total_sell = strong_sell + sell
    buy_pct  = total_buy  / total
    sell_pct = total_sell / total
    if buy_pct > 0.60:
        consensus = "Strong Buy"
    elif buy_pct > 0.40:
        consensus = "Buy"
    elif sell_pct > 0.60:
        consensus = "Strong Sell"
    elif sell_pct > 0.40:
        consensus = "Sell"
    else:
        consensus = "Hold"
    return {"buy": total_buy, "hold": hold, "sell": total_sell, "consensus": consensus}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@app.get("/api/ticker/{symbol}")
def get_ticker(symbol: str):
    symbol = symbol.upper().strip()

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        if not (info.get("longName") or info.get("shortName")):
            raise HTTPException(
                status_code=404,
                detail=f"Ticker '{symbol}' not found or has no data.",
            )

        # 1-year daily history for all TA + chart
        hist = ticker.history(period="1y")
        if hist.empty:
            raise HTTPException(
                status_code=404,
                detail=f"No price history found for '{symbol}'.",
            )

        close = hist["Close"]

        # --- Technical indicators ---
        rsi_series  = calc_rsi(close, 14)
        macd_line, signal_line, macd_hist_series = calc_macd(close)
        sma20_series  = calc_sma(close, 20)
        sma50_series  = calc_sma(close, 50)
        sma200_series = calc_sma(close, 200)

        # --- Header ---
        current_price = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        change        = clean_float(info.get("regularMarketChange"))
        change_pct    = clean_float(info.get("regularMarketChangePercent"))
        bid           = clean_float(info.get("bid") or None)
        ask           = clean_float(info.get("ask") or None)
        spread        = clean_float((ask - bid) if (bid and ask) else None)

        rmt = info.get("regularMarketTime")
        last_updated = (
            datetime.datetime.fromtimestamp(rmt, tz=datetime.timezone.utc).isoformat()
            if rmt else None
        )

        # --- Price stats ---
        day_high  = clean_float(info.get("dayHigh"))
        day_low   = clean_float(info.get("dayLow"))
        wk52_high = clean_float(info.get("fiftyTwoWeekHigh"))
        wk52_low  = clean_float(info.get("fiftyTwoWeekLow"))

        week52_pct = None
        if wk52_high and wk52_low and wk52_high != wk52_low and current_price:
            week52_pct = round(
                (current_price - wk52_low) / (wk52_high - wk52_low) * 100, 2
            )
            week52_pct = max(0.0, min(100.0, week52_pct))

        vwap = None
        try:
            intraday = ticker.history(period="1d", interval="1m")
            if not intraday.empty and intraday["Volume"].sum() > 0:
                vwap = clean_float(
                    float(
                        (intraday["Close"] * intraday["Volume"]).sum()
                        / intraday["Volume"].sum()
                    )
                )
        except Exception:
            pass
        if vwap is None and day_high and day_low and current_price:
            vwap = clean_float((day_high + day_low + current_price) / 3)

        # --- Volume ---
        current_vol = clean_float(info.get("volume") or info.get("regularMarketVolume") or None)
        avg_30d_vol = clean_float(hist["Volume"].tail(30).mean())
        vol_ratio   = (
            clean_float(current_vol / avg_30d_vol)
            if (current_vol and avg_30d_vol and avg_30d_vol > 0)
            else None
        )

        # --- Technicals: last values ---
        rsi_val = safe_last(rsi_series)
        rsi_label = None
        if rsi_val is not None:
            rsi_label = "Overbought" if rsi_val > 70 else ("Oversold" if rsi_val < 30 else "Neutral")

        macd_val  = safe_last(macd_line)
        macd_sig  = safe_last(signal_line)
        macd_hist = safe_last(macd_hist_series)
        macd_dir  = (
            "Bullish" if (macd_hist is not None and macd_hist > 0)
            else "Bearish" if macd_hist is not None
            else None
        )

        sma20_val  = safe_last(sma20_series)
        sma50_val  = safe_last(sma50_series)
        sma200_val = safe_last(sma200_series)

        def sma_position(v):
            if v is None or current_price is None:
                return None
            return "Above" if current_price > v else "Below"

        # Beta vs SPY
        beta = None
        try:
            spy_hist = yf.Ticker("SPY").history(period="1y")
            if not spy_hist.empty:
                stock_ret = close.pct_change().dropna()
                spy_ret   = spy_hist["Close"].pct_change().dropna()
                aligned   = pd.concat([stock_ret, spy_ret], axis=1, join="inner").dropna()
                if len(aligned) > 30:
                    cov_m = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
                    if cov_m[1, 1] != 0:
                        beta = clean_float(cov_m[0, 1] / cov_m[1, 1])
        except Exception:
            pass

        # Historical Volatility 30d
        hv30d = None
        try:
            log_ret = np.log(close / close.shift(1)).dropna()
            if len(log_ret) >= 30:
                hv30d = clean_float(float(log_ret.tail(30).std() * math.sqrt(252) * 100))
        except Exception:
            pass

        # --- Analyst ---
        analyst_base = compute_consensus(ticker.recommendations_summary)
        target_price   = clean_float(info.get("targetMeanPrice"))
        implied_upside = None
        if target_price and current_price and current_price > 0:
            implied_upside = clean_float((target_price - current_price) / current_price * 100)

        # --- Chart: last 6 months ---
        six_months_ago = hist.index[-1] - pd.DateOffset(months=6)
        chart_df = hist[hist.index >= six_months_ago]

        prices = [round(float(v), 4) for v in chart_df["Close"]]
        dates  = chart_df.index.strftime("%Y-%m-%d").tolist()
        sma20  = chart_col(sma20_series.reindex(chart_df.index))
        sma50  = chart_col(sma50_series.reindex(chart_df.index))
        sma200 = chart_col(sma200_series.reindex(chart_df.index))

        # --- Assemble response ---
        response = {
            "header": {
                "company_name":  info.get("longName") or info.get("shortName"),
                "ticker":        symbol,
                "exchange":      info.get("exchange"),
                "sector":        info.get("sector"),
                "industry":      info.get("industry"),
                "current_price": current_price,
                "change":        change,
                "change_pct":    change_pct,
                "bid":           bid,
                "ask":           ask,
                "spread":        spread,
                "last_updated":  last_updated,
            },
            "price_stats": {
                "open":        clean_float(info.get("open")),
                "prev_close":  clean_float(info.get("previousClose")),
                "day_high":    day_high,
                "day_low":     day_low,
                "week52_high": wk52_high,
                "week52_low":  wk52_low,
                "week52_pct":  week52_pct,
                "vwap":        vwap,
            },
            "volume": {
                "current": current_vol,
                "avg_30d": avg_30d_vol,
                "ratio":   vol_ratio,
            },
            "fundamentals": {
                "market_cap":     clean_float(info.get("marketCap")),
                "pe_trailing":    clean_float(info.get("trailingPE")),
                "pe_forward":     clean_float(info.get("forwardPE")),
                "eps_ttm":        clean_float(info.get("trailingEps")),
                "price_to_book":  clean_float(info.get("priceToBook")),
                "ev_ebitda":      clean_float(info.get("enterpriseToEbitda")),
                "revenue_ttm":    clean_float(info.get("totalRevenue")),
                "ebitda_margin":  clean_float(info.get("ebitdaMargins")),
                "dividend_yield": clean_float(info.get("dividendYield")),
            },
            "technicals": {
                "rsi":   {"value": rsi_val,  "label": rsi_label},
                "macd":  {
                    "value":     macd_val,
                    "signal":    macd_sig,
                    "histogram": macd_hist,
                    "direction": macd_dir,
                },
                "sma20":  {"value": sma20_val,  "position": sma_position(sma20_val)},
                "sma50":  {"value": sma50_val,  "position": sma_position(sma50_val)},
                "sma200": {"value": sma200_val, "position": sma_position(sma200_val)},
                "beta":   beta,
                "hv30d":  hv30d,
            },
            "analyst": {
                **analyst_base,
                "target_price":   target_price,
                "implied_upside": implied_upside,
            },
            "chart": {
                "dates":  dates,
                "prices": prices,
                "sma20":  sma20,
                "sma50":  sma50,
                "sma200": sma200,
            },
        }

        return deep_clean(response)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data fetch failed: {str(e)}")


# ---------------------------------------------------------------------------
# Portfolio endpoint
# ---------------------------------------------------------------------------

class PortfolioPosition(BaseModel):
    ticker: str
    shares: float
    avg_cost: float

class PortfolioRequest(BaseModel):
    positions: List[PortfolioPosition]


@app.post("/api/portfolio")
def get_portfolio(req: PortfolioRequest):
    if not req.positions:
        raise HTTPException(status_code=400, detail="No positions provided.")

    # Fetch SPY once for beta calculations
    spy_returns = None
    spy_hist = None
    try:
        spy_hist = yf.Ticker("SPY").history(period="1y")
        if not spy_hist.empty:
            spy_returns = spy_hist["Close"].pct_change().dropna()
    except Exception:
        pass

    position_data = []
    hist_map: dict = {}

    for pos in req.positions:
        ticker = pos.ticker.upper().strip()
        try:
            t = yf.Ticker(ticker)
            info = t.info
            hist = t.history(period="1y")

            current_price = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
            change        = clean_float(info.get("regularMarketChange"))
            change_pct    = clean_float(info.get("regularMarketChangePercent"))
            company_name  = info.get("longName") or info.get("shortName") or ticker
            sector        = info.get("sector") or "Unknown"

            market_value   = clean_float(pos.shares * current_price) if current_price else None
            cost_basis     = clean_float(pos.shares * pos.avg_cost)
            pnl_dollar     = clean_float(market_value - cost_basis) if market_value is not None else None
            pnl_pct        = clean_float(pnl_dollar / cost_basis * 100) if (pnl_dollar is not None and cost_basis and cost_basis != 0) else None
            day_chg_dollar = clean_float(pos.shares * change) if change is not None else None

            # Per-position beta
            beta = None
            if spy_returns is not None and not hist.empty:
                try:
                    sr = hist["Close"].pct_change().dropna()
                    al = pd.concat([sr, spy_returns], axis=1, join="inner").dropna()
                    if len(al) > 30:
                        cm = np.cov(al.iloc[:, 0], al.iloc[:, 1])
                        if cm[1, 1] != 0:
                            beta = clean_float(cm[0, 1] / cm[1, 1])
                except Exception:
                    pass

            if not hist.empty:
                hist_map[ticker] = hist["Close"]

            position_data.append({
                "ticker": ticker, "company_name": company_name, "sector": sector,
                "shares": pos.shares, "avg_cost": pos.avg_cost,
                "current_price": current_price, "market_value": market_value,
                "cost_basis": cost_basis, "pnl_dollar": pnl_dollar, "pnl_pct": pnl_pct,
                "day_change_dollar": day_chg_dollar, "day_change_pct": change_pct,
                "beta": beta, "weight": None,
            })
        except Exception:
            position_data.append({
                "ticker": ticker, "company_name": ticker, "sector": "Unknown",
                "shares": pos.shares, "avg_cost": pos.avg_cost,
                "current_price": None, "market_value": None,
                "cost_basis": clean_float(pos.shares * pos.avg_cost),
                "pnl_dollar": None, "pnl_pct": None,
                "day_change_dollar": None, "day_change_pct": None,
                "beta": None, "weight": None,
            })

    # Totals
    total_mv   = sum(p["market_value"] for p in position_data if p["market_value"])
    total_cb   = sum(p["cost_basis"]   for p in position_data if p["cost_basis"])
    total_pnl  = clean_float(total_mv - total_cb) if (total_mv and total_cb) else None
    total_pnl_pct = clean_float(total_pnl / total_cb * 100) if (total_pnl and total_cb and total_cb != 0) else None
    total_day  = sum(p["day_change_dollar"] for p in position_data if p["day_change_dollar"])
    prev_mv    = (total_mv - total_day) if (total_mv and total_day) else None
    total_day_pct = clean_float(total_day / prev_mv * 100) if (total_day and prev_mv and prev_mv != 0) else None

    # Weights
    for p in position_data:
        if p["market_value"] and total_mv and total_mv > 0:
            p["weight"] = clean_float(p["market_value"] / total_mv * 100)

    # Sector breakdown
    sector_weights: dict = {}
    for p in position_data:
        s = p["sector"] or "Unknown"
        sector_weights[s] = sector_weights.get(s, 0) + (p["weight"] or 0)

    # Concentration flags (>20%)
    concentration_flags = [p["ticker"] for p in position_data if p["weight"] and p["weight"] > 20]

    # Weighted portfolio beta
    portfolio_beta = None
    valid_betas = [p for p in position_data if p["beta"] is not None and p["weight"] is not None]
    if valid_betas:
        portfolio_beta = clean_float(sum(p["weight"] / 100 * p["beta"] for p in valid_betas))

    # Portfolio weighted returns
    portfolio_hv30d = None
    sharpe          = None
    max_drawdown    = None
    port_ret_series = None

    if hist_map and total_mv and total_mv > 0:
        try:
            frames, wts = [], []
            for p in position_data:
                tk = p["ticker"]
                if tk in hist_map and p["weight"] is not None:
                    frames.append(hist_map[tk].pct_change())
                    wts.append(p["weight"] / 100)
            if frames:
                combined = pd.concat(frames, axis=1, join="inner").dropna()
                if len(combined) > 30 and combined.shape[1] == len(wts):
                    wa = np.array(wts); wa = wa / wa.sum()
                    port_ret = combined.values @ wa
                    port_ret_series = pd.Series(port_ret, index=combined.index)

                    log_ret = np.log(1 + port_ret_series).dropna()
                    if len(log_ret) >= 30:
                        portfolio_hv30d = clean_float(float(log_ret.tail(30).std() * math.sqrt(252) * 100))

                    if portfolio_hv30d and portfolio_hv30d > 0:
                        ann_ret = float((1 + port_ret_series.mean()) ** 252 - 1) * 100
                        sharpe  = clean_float((ann_ret - 5.0) / portfolio_hv30d)

                    cum  = (1 + port_ret_series).cumprod()
                    rmax = cum.cummax()
                    max_drawdown = clean_float(float(((cum - rmax) / rmax).min()) * 100)
        except Exception:
            pass

    # Correlation matrix
    correlation_matrix = None
    if len(hist_map) >= 2:
        try:
            ret_dict = {tk: hist_map[tk].pct_change() for tk in hist_map}
            comb = pd.concat(list(ret_dict.values()), axis=1, join="inner")
            comb.columns = list(ret_dict.keys())
            comb = comb.dropna()
            corr = comb.corr()
            correlation_matrix = {
                "tickers": list(corr.columns),
                "values": [[clean_float(v) for v in row] for row in corr.values.tolist()],
            }
        except Exception:
            pass

    # Portfolio chart (1y, normalized)
    chart_data = None
    if port_ret_series is not None and total_mv:
        try:
            cum    = (1 + port_ret_series).cumprod()
            pv     = cum / cum.iloc[-1] * total_mv
            dates  = [d.strftime("%Y-%m-%d") for d in pv.index]
            prices = [round(float(v), 2) for v in pv.values]

            spy_prices = None
            if spy_hist is not None and not spy_hist.empty:
                spy_al = spy_hist["Close"].reindex(pv.index)
                if spy_al.notna().any():
                    spy_norm  = spy_al / spy_al.dropna().iloc[-1] * total_mv
                    spy_prices = [round(float(v), 2) if not math.isnan(float(v)) else None for v in spy_norm.values]

            chart_data = {"dates": dates, "portfolio": prices, "spy": spy_prices}
        except Exception:
            pass

    response = {
        "positions": position_data,
        "totals": {
            "market_value": total_mv, "cost_basis": total_cb,
            "pnl_dollar": total_pnl, "pnl_pct": total_pnl_pct,
            "day_change_dollar": total_day if total_day else None,
            "day_change_pct": total_day_pct,
        },
        "metrics": {
            "total_value": total_mv, "beta": portfolio_beta,
            "hv30d": portfolio_hv30d, "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "num_positions": len(position_data),
            "concentration_flags": concentration_flags,
        },
        "sectors": sector_weights,
        "correlation": correlation_matrix,
        "chart": chart_data,
    }
    return deep_clean(response)


# ---------------------------------------------------------------------------
# News endpoint
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("Reuters Top News", "https://feeds.reuters.com/reuters/topNews"),
    ("Financial Times",  "https://rss.ft.com/rss/home/us"),
    ("BBC Business",     "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("AP Finance",       "https://rss.app/feeds/AP-finance.xml"),
]

_news_cache: dict = {"ts": 0.0, "data": None}
NEWS_CACHE_TTL = 15 * 60  # 15 minutes


def _parse_feed_date(entry):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime.datetime(*t[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                pass
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _title_key(title: str) -> str:
    return re.sub(r"\W+", " ", title.lower()).strip()


def _fetch_articles() -> list[dict]:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
    seen_keys: set[str] = set()
    articles = []

    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                pub = _parse_feed_date(entry)
                if pub and pub < cutoff:
                    continue
                title = _strip_html(getattr(entry, "title", "") or "")
                if not title:
                    continue
                key = _title_key(title)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                summary = _strip_html(getattr(entry, "summary", "") or
                                      getattr(entry, "description", "") or "")
                link = getattr(entry, "link", "") or ""
                articles.append({
                    "title":        title,
                    "summary":      summary[:500],
                    "source":       source_name,
                    "url":          link,
                    "published_at": pub.isoformat() if pub else None,
                })
        except Exception:
            continue

    return articles


_MACRO_KEYWORDS = [
    "fed", "federal reserve", "interest rate", "inflation", "cpi", "pce", "gdp",
    "central bank", "ecb", "boe", "boj", "rate hike", "rate cut", "quantitative",
    "sanctions", "tariff", "trade war", "geopolit", "war", "conflict", "military",
    "oil", "opec", "gas", "energy", "supply chain", "strait", "hormuz",
    "ai ", "artificial intelligence", "regulation", "antitrust",
    "recession", "unemployment", "jobs", "nonfarm", "payroll",
    "treasury", "yield", "bond", "debt", "deficit", "fiscal",
    "election", "political", "government", "congress", "senate",
    "bank", "financial", "market", "stock", "equity", "currency", "dollar", "euro",
]
_EXCLUDE_KEYWORDS = [
    "sport", "soccer", "football", "nfl", "nba", "nhl", "cricket",
    "celebrity", "fashion", "lifestyle", "recipe", "travel", "weather",
    "movie", "film", "music", "entertainment",
]

_CAT_KEYWORDS = {
    "Fed/Monetary Policy": ["fed", "federal reserve", "interest rate", "rate hike", "rate cut", "central bank", "ecb", "boe", "boj", "quantitative", "monetary", "inflation", "cpi", "pce"],
    "Geopolitics":         ["war", "conflict", "military", "sanction", "geopolit", "nato", "ukraine", "russia", "china", "iran", "middle east", "taiwan", "north korea"],
    "Commodities":         ["oil", "opec", "gas", "energy", "crude", "commodity", "gold", "silver", "wheat", "supply chain", "hormuz"],
    "Tech/AI":             ["ai ", "artificial intelligence", "openai", "nvidia", "chip", "semiconductor", "regulation", "antitrust", "tech"],
    "Markets":             ["market", "stock", "equity", "rally", "selloff", "crash", "volatility", "treasury", "yield", "bond", "dollar", "currency"],
    "Macro Economy":       ["gdp", "recession", "unemployment", "jobs", "payroll", "fiscal", "deficit", "debt", "trade", "tariff", "growth"],
}


def _keyword_filter(articles: list[dict]) -> list[dict]:
    """Fallback filter used when ANTHROPIC_API_KEY is not set."""
    results = []
    for i, a in enumerate(articles):
        text = (a["title"] + " " + a["summary"]).lower()
        if any(kw in text for kw in _EXCLUDE_KEYWORDS):
            continue
        hit_count = sum(1 for kw in _MACRO_KEYWORDS if kw in text)
        if hit_count < 2:
            continue

        category = "Macro Economy"
        for cat, kws in _CAT_KEYWORDS.items():
            if any(kw in text for kw in kws):
                category = cat
                break

        score = min(7 + min(hit_count - 2, 2), 9)
        results.append({
            **a,
            "importance_score": score,
            "category": category,
            "market_impact": "",
            "sentiment": "Neutral",
        })

    results.sort(key=lambda x: x["importance_score"], reverse=True)
    return results[:20]


def _claude_filter(articles: list[dict]) -> list[dict]:
    if not articles:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _keyword_filter(articles)

    batch_text = "\n".join(
        f'[{i}] TITLE: {a["title"]}\nSUMMARY: {a["summary"]}'
        for i, a in enumerate(articles)
    )

    system = (
        "You are a financial news filter for a professional trading terminal.\n"
        "Your job is to identify only macro-relevant, market-moving news.\n\n"
        "INCLUDE: Fed decisions, interest rates, inflation data, central bank policy, "
        "geopolitical conflicts, oil/gas supply disruptions, Strait of Hormuz, wars, "
        "sanctions, major AI breakthroughs or regulation, systemic financial risk, "
        "large sovereign events, natural disasters with economic impact, "
        "major political elections or instability.\n\n"
        "EXCLUDE: individual company earnings (unless systemic), crypto minor moves, "
        "sports, lifestyle, celebrity, regional politics with no macro impact, "
        "routine economic data releases with no surprise.\n\n"
        "For each article that passes the filter, return a JSON array with:\n"
        "- id (original index)\n"
        "- importance_score (1-10, where 10 = market-moving event)\n"
        "- category: one of [Fed/Monetary Policy, Geopolitics, Commodities, Tech/AI, Markets, Macro Economy]\n"
        "- market_impact: 2-sentence explanation of potential market impact written for a trader\n"
        "- sentiment: Positive / Negative / Neutral (relative to risk assets)\n\n"
        "Only include articles with importance_score >= 7.\n"
        "Return only valid JSON array, no markdown, no preamble."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": batch_text}],
        )
        raw = msg.content[0].text.strip()
        scored = json.loads(raw)
    except Exception:
        return []

    enriched = []
    for item in scored:
        idx = item.get("id")
        if idx is None or not isinstance(idx, int) or idx >= len(articles):
            continue
        score = item.get("importance_score", 0)
        if score < 7:
            continue
        art = dict(articles[idx])
        art["importance_score"] = score
        art["category"]        = item.get("category", "Markets")
        art["market_impact"]   = item.get("market_impact", "")
        art["sentiment"]       = item.get("sentiment", "Neutral")
        enriched.append(art)

    enriched.sort(key=lambda x: x["importance_score"], reverse=True)
    return enriched[:20]


@app.get("/api/news")
def get_news():
    now = time.time()
    if _news_cache["data"] is not None and (now - _news_cache["ts"]) < NEWS_CACHE_TTL:
        return _news_cache["data"]

    articles = _fetch_articles()
    filtered = _claude_filter(articles)

    result = {
        "articles": filtered,
        "total_fetched": len(articles),
        "cached_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _news_cache["ts"]   = now
    _news_cache["data"] = result
    return result


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
