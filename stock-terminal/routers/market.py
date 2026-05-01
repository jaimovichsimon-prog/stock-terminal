import math
import datetime
import pandas as pd
import numpy as np
import yfinance as yf

from fastapi import APIRouter, HTTPException

from config import logger
from utils.market_data import clean_float, deep_clean, safe_last, chart_col
from utils.indicators import calc_rsi, calc_macd, calc_sma, compute_consensus
from services.cache import macro_cache, options_cache, sector_cache

router = APIRouter()

MACRO_TICKERS = {
    "S&P 500":   "^GSPC",
    "Nasdaq":    "^IXIC",
    "VIX":       "^VIX",
    "10Y Yield": "^TNX",
    "DXY":       "DX-Y.NYB",
    "WTI Oil":   "CL=F",
    "Gold":      "GC=F",
    "BTC":       "BTC-USD",
}


# ---------------------------------------------------------------------------
# /api/ticker/{symbol}
# ---------------------------------------------------------------------------
@router.get("/ticker/{symbol}")
def get_ticker(symbol: str):
    symbol = symbol.upper().strip()
    try:
        ticker = yf.Ticker(symbol)
        info   = ticker.info

        if not (info.get("longName") or info.get("shortName")):
            raise HTTPException(status_code=404, detail=f"Ticker '{symbol}' not found or has no data.")

        hist = ticker.history(period="1y")
        if hist.empty:
            raise HTTPException(status_code=404, detail=f"No price history found for '{symbol}'.")

        close = hist["Close"]

        rsi_series               = calc_rsi(close, 14)
        macd_line, signal_line, macd_hist_series = calc_macd(close)
        sma20_series             = calc_sma(close, 20)
        sma50_series             = calc_sma(close, 50)
        sma200_series            = calc_sma(close, 200)

        current_price = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        change        = clean_float(info.get("regularMarketChange"))
        change_pct    = clean_float(info.get("regularMarketChangePercent"))
        bid           = clean_float(info.get("bid") or None)
        ask           = clean_float(info.get("ask") or None)
        spread        = clean_float((ask - bid) if (bid and ask) else None)

        rmt          = info.get("regularMarketTime")
        last_updated = (
            datetime.datetime.fromtimestamp(rmt, tz=datetime.timezone.utc).isoformat()
            if rmt else None
        )

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
                    float((intraday["Close"] * intraday["Volume"]).sum() / intraday["Volume"].sum())
                )
        except Exception:
            logger.warning("VWAP intraday fetch failed for %s", symbol, exc_info=True)
        if vwap is None and day_high and day_low and current_price:
            vwap = clean_float((day_high + day_low + current_price) / 3)

        current_vol = clean_float(info.get("volume") or info.get("regularMarketVolume") or None)
        avg_30d_vol = clean_float(hist["Volume"].tail(30).mean())
        vol_ratio   = (
            clean_float(current_vol / avg_30d_vol)
            if (current_vol and avg_30d_vol and avg_30d_vol > 0) else None
        )

        rsi_val   = safe_last(rsi_series)
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
            logger.warning("Beta calculation failed for %s", symbol, exc_info=True)

        hv30d = None
        try:
            log_ret = np.log(close / close.shift(1)).dropna()
            if len(log_ret) >= 30:
                hv30d = clean_float(float(log_ret.tail(30).std() * math.sqrt(252) * 100))
        except Exception:
            logger.warning("HV30d calculation failed for %s", symbol, exc_info=True)

        analyst_base   = compute_consensus(ticker.recommendations_summary)
        target_price   = clean_float(info.get("targetMeanPrice"))
        implied_upside = None
        if target_price and current_price and current_price > 0:
            implied_upside = clean_float((target_price - current_price) / current_price * 100)

        six_months_ago = hist.index[-1] - pd.DateOffset(months=6)
        chart_df = hist[hist.index >= six_months_ago]
        prices   = [round(float(v), 4) for v in chart_df["Close"]]
        dates    = chart_df.index.strftime("%Y-%m-%d").tolist()
        sma20    = chart_col(sma20_series.reindex(chart_df.index))
        sma50    = chart_col(sma50_series.reindex(chart_df.index))
        sma200   = chart_col(sma200_series.reindex(chart_df.index))

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
                "rsi":  {"value": rsi_val, "label": rsi_label},
                "macd": {
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
        logger.error("Ticker fetch failed for %s", symbol, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Data fetch failed: {str(e)}")


# ---------------------------------------------------------------------------
# /api/macro
# ---------------------------------------------------------------------------
@router.get("/macro")
def get_macro():
    cached = macro_cache.get("main")
    if cached is not None:
        return cached

    indicators = []
    for name, sym in MACRO_TICKERS.items():
        try:
            info       = yf.Ticker(sym).info
            price      = clean_float(info.get("regularMarketPrice") or info.get("currentPrice"))
            change     = clean_float(info.get("regularMarketChange"))
            change_pct = clean_float(info.get("regularMarketChangePercent"))
            prev_close = clean_float(info.get("previousClose") or info.get("regularMarketPreviousClose"))
            indicators.append({
                "name": name, "ticker": sym,
                "price": price, "change": change,
                "change_pct": change_pct, "prev_close": prev_close,
            })
        except Exception:
            logger.warning("Macro fetch failed for %s", sym, exc_info=True)
            indicators.append({
                "name": name, "ticker": sym,
                "price": None, "change": None, "change_pct": None, "prev_close": None,
            })

    result = deep_clean({"indicators": indicators})
    macro_cache.set("main", result)
    return result


# ---------------------------------------------------------------------------
# /api/watchlist  (public — comma-separated tickers query param)
# ---------------------------------------------------------------------------
@router.get("/watchlist")
def get_public_watchlist(tickers: str = ""):
    if not tickers.strip():
        return {"positions": []}

    syms    = [t.strip().upper() for t in tickers.split(",") if t.strip()][:30]
    results = []
    for sym in syms:
        try:
            info = yf.Ticker(sym).info
            results.append({
                "ticker":        sym,
                "company_name":  info.get("longName") or info.get("shortName") or sym,
                "sector":        info.get("sector"),
                "current_price": clean_float(info.get("currentPrice") or info.get("regularMarketPrice")),
                "change":        clean_float(info.get("regularMarketChange")),
                "change_pct":    clean_float(info.get("regularMarketChangePercent")),
                "market_cap":    clean_float(info.get("marketCap")),
                "pe_trailing":   clean_float(info.get("trailingPE")),
                "volume":        clean_float(info.get("volume") or info.get("regularMarketVolume")),
                "day_high":      clean_float(info.get("dayHigh")),
                "day_low":       clean_float(info.get("dayLow")),
                "week52_high":   clean_float(info.get("fiftyTwoWeekHigh")),
                "week52_low":    clean_float(info.get("fiftyTwoWeekLow")),
            })
        except Exception:
            logger.warning("Watchlist fetch failed for %s", sym, exc_info=True)
            results.append({
                "ticker": sym, "company_name": sym,
                "sector": None, "current_price": None, "change": None, "change_pct": None,
                "market_cap": None, "pe_trailing": None, "volume": None,
                "day_high": None, "day_low": None, "week52_high": None, "week52_low": None,
            })

    return deep_clean({"positions": results})


# ---------------------------------------------------------------------------
# /api/options/{symbol}
# ---------------------------------------------------------------------------
@router.get("/options/{symbol}")
def get_options(symbol: str):
    symbol = symbol.upper().strip()

    cached = options_cache.get(symbol)
    if cached is not None:
        return cached

    try:
        ticker_obj    = yf.Ticker(symbol)
        info          = ticker_obj.info
        current_price = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if current_price is None:
            raise HTTPException(status_code=404, detail="No price data for this symbol.")

        expirations = ticker_obj.options
        if not expirations:
            result = {"available": False, "symbol": symbol, "current_price": current_price}
            options_cache.set(symbol, result)
            return result

        today = datetime.date.today()

        def days_to(exp_str: str) -> int:
            try:
                return (datetime.datetime.strptime(exp_str, "%Y-%m-%d").date() - today).days
            except Exception:
                return 999

        def exp_label(exp_str: str) -> str:
            try:
                return datetime.datetime.strptime(exp_str, "%Y-%m-%d").strftime("%d %b")
            except Exception:
                return exp_str

        chains: dict = {}
        for exp in expirations[:8]:
            try:
                chains[exp] = ticker_obj.option_chain(exp)
            except Exception:
                logger.warning("Option chain fetch failed for %s exp=%s", symbol, exp, exc_info=True)

        # ── Implied Moves ────────────────────────────────────────────────────
        implied_moves = []
        for exp, chain in chains.items():
            try:
                calls  = chain.calls
                puts   = chain.puts
                if calls.empty or puts.empty:
                    continue
                common = set(calls["strike"].tolist()) & set(puts["strike"].tolist())
                if not common:
                    continue
                atm = min(common, key=lambda s: abs(s - current_price))

                def get_mid(df, strike):
                    row = df[df["strike"] == strike]
                    if row.empty:
                        return None
                    r   = row.iloc[0]
                    bid = clean_float(r.get("bid"))
                    ask = clean_float(r.get("ask"))
                    if bid is not None and ask is not None and (bid + ask) > 0:
                        return (bid + ask) / 2
                    return clean_float(r.get("lastPrice"))

                call_mid = get_mid(calls, atm)
                put_mid  = get_mid(puts, atm)
                if call_mid is None or put_mid is None:
                    continue
                implied_moves.append({
                    "expiration":       exp,
                    "exp_label":        exp_label(exp),
                    "days_to_expiry":   days_to(exp),
                    "implied_move_pct": clean_float(round((call_mid + put_mid) / current_price * 100, 2)),
                    "atm_strike":       clean_float(atm),
                    "atm_call_mid":     clean_float(round(call_mid, 2)),
                    "atm_put_mid":      clean_float(round(put_mid, 2)),
                })
            except Exception:
                logger.warning("Implied move calc failed for %s exp=%s", symbol, exp, exc_info=True)

        implied_moves.sort(key=lambda x: x["days_to_expiry"])

        # ── IV Smiles ────────────────────────────────────────────────────────
        smiles: dict         = {}
        default_smile_exp    = None

        for exp, chain in chains.items():
            try:
                calls = chain.calls
                puts  = chain.puts

                def build_map(df):
                    m = {}
                    for _, row in df.iterrows():
                        s  = clean_float(row["strike"])
                        iv = clean_float(row.get("impliedVolatility"))
                        if s is None or iv is None or iv < 0.001:
                            continue
                        iv_pct = round(iv * 100, 2)
                        if iv_pct <= 0:
                            continue
                        m[s] = {"iv": iv_pct, "volume": clean_float(row.get("volume")) or 0, "oi": clean_float(row.get("openInterest")) or 0}
                    return m

                call_map    = build_map(calls)
                put_map     = build_map(puts)
                all_strikes = sorted(set(call_map) | set(put_map))
                if len(all_strikes) <= 5:
                    continue
                atm = min(all_strikes, key=lambda s: abs(s - current_price))

                strikes_data = []
                for s in all_strikes:
                    cd = call_map.get(s, {})
                    pd_ = put_map.get(s, {})
                    strikes_data.append({
                        "strike":      s,
                        "moneyness":   clean_float(round(s / current_price * 100, 1)),
                        "call_iv":     cd.get("iv"),
                        "put_iv":      pd_.get("iv"),
                        "call_volume": cd.get("volume"),
                        "put_volume":  pd_.get("volume"),
                        "call_oi":     cd.get("oi"),
                        "put_oi":      pd_.get("oi"),
                        "is_atm":      s == atm,
                    })

                atm_idx   = all_strikes.index(atm)
                below_ivs = [put_map[s]["iv"] for s in all_strikes[max(0, atm_idx-2):atm_idx] if s in put_map]
                above_ivs = [put_map[s]["iv"] for s in all_strikes[atm_idx+1:atm_idx+3]       if s in put_map]
                skew_label = None
                if below_ivs and above_ivs:
                    diff = sum(below_ivs)/len(below_ivs) - sum(above_ivs)/len(above_ivs)
                    if diff > 3:
                        skew_label = "PUT SKEW — fear premium detected"
                    elif diff < -3:
                        skew_label = "CALL SKEW — momentum/squeeze pricing"
                    else:
                        skew_label = "CLASSIC SMILE"

                smiles[exp] = {
                    "expiration": exp, "exp_label": exp_label(exp),
                    "days_to_expiry": days_to(exp),
                    "strikes": strikes_data, "atm_strike": clean_float(atm),
                    "skew_label": skew_label,
                }
                if default_smile_exp is None:
                    default_smile_exp = exp
            except Exception:
                logger.warning("IV smile calc failed for %s exp=%s", symbol, exp, exc_info=True)

        # ── Volatility Surface ───────────────────────────────────────────────
        surface_data = None
        try:
            surface_exps = list(chains.keys())
            strike_data: dict = {}

            for exp, chain in chains.items():
                def iv_oi_map(df):
                    m = {}
                    for _, row in df.iterrows():
                        s  = clean_float(row["strike"])
                        iv = clean_float(row.get("impliedVolatility"))
                        if s and iv and iv >= 0.001:
                            iv_pct = iv * 100
                            if iv_pct > 0:
                                m[s] = {"iv": iv_pct, "oi": clean_float(row.get("openInterest")) or 0}
                    return m

                c_map = iv_oi_map(chain.calls)
                p_map = iv_oi_map(chain.puts)
                for s in set(c_map) | set(p_map):
                    civ    = c_map.get(s, {}).get("iv")
                    piv    = p_map.get(s, {}).get("iv")
                    avg_iv = (civ + piv) / 2 if (civ and piv) else (civ or piv)
                    if avg_iv is None:
                        continue
                    if s not in strike_data:
                        strike_data[s] = {}
                    strike_data[s][exp] = {
                        "avg_iv":  round(avg_iv, 1),
                        "call_oi": c_map.get(s, {}).get("oi"),
                        "put_oi":  p_map.get(s, {}).get("oi"),
                    }

            valid_strikes = sorted(s for s, d in strike_data.items() if len(d) >= 3)
            surface_rows  = []
            for pct in [0.90, 0.95, 1.00, 1.05, 1.10]:
                if not valid_strikes:
                    break
                closest = min(valid_strikes, key=lambda s: abs(s - current_price * pct))
                cells   = []
                for exp in surface_exps:
                    cell = strike_data.get(closest, {}).get(exp, {})
                    cells.append({
                        "expiration": exp, "exp_label": exp_label(exp),
                        "avg_iv": cell.get("avg_iv"), "call_oi": cell.get("call_oi"),
                        "put_oi": cell.get("put_oi"), "is_atm": abs(pct - 1.0) < 0.001,
                    })
                surface_rows.append({
                    "moneyness_pct":   pct * 100,
                    "moneyness_label": f"{int(pct * 100)}%",
                    "strike":          clean_float(closest),
                    "cells":           cells,
                })

            all_ivs      = [c["avg_iv"] for r in surface_rows for c in r["cells"] if c.get("avg_iv")]
            surface_data = {
                "rows":        surface_rows,
                "expirations": [{"expiration": e, "exp_label": exp_label(e)} for e in surface_exps],
                "iv_min":      clean_float(round(min(all_ivs), 1)) if all_ivs else 0,
                "iv_max":      clean_float(round(max(all_ivs), 1)) if all_ivs else 100,
            }
        except Exception:
            logger.warning("Volatility surface failed for %s", symbol, exc_info=True)

        is_sparse = len(implied_moves) < 3 or len(smiles) < 2
        result = deep_clean({
            "available":             True,
            "symbol":                symbol,
            "current_price":         current_price,
            "implied_moves":         implied_moves,
            "smiles":                smiles,
            "default_smile_exp":     default_smile_exp,
            "available_expirations": [
                {"expiration": e, "exp_label": exp_label(e), "days_to_expiry": days_to(e)}
                for e in chains.keys()
            ],
            "surface":   surface_data,
            "is_sparse": is_sparse,
        })
        options_cache.set(symbol, result)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Options fetch failed for %s", symbol, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Options fetch failed: {str(e)}")
