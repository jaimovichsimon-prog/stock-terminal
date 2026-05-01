import math
from typing import List

import numpy as np
import pandas as pd
import yfinance as yf

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import logger
from utils.market_data import clean_float, deep_clean

router = APIRouter()


class PortfolioPositionIn(BaseModel):
    ticker:   str
    shares:   float
    avg_cost: float

class PortfolioRequest(BaseModel):
    positions: List[PortfolioPositionIn]


@router.post("/portfolio")
def get_portfolio_analysis(req: PortfolioRequest):
    if not req.positions:
        raise HTTPException(status_code=400, detail="No positions provided.")

    spy_returns = None
    spy_hist    = None
    try:
        spy_hist = yf.Ticker("SPY").history(period="1y")
        if not spy_hist.empty:
            spy_returns = spy_hist["Close"].pct_change().dropna()
    except Exception:
        logger.warning("SPY fetch failed for portfolio analysis", exc_info=True)

    position_data = []
    hist_map: dict = {}

    for pos in req.positions:
        ticker = pos.ticker.upper().strip()
        try:
            t             = yf.Ticker(ticker)
            info          = t.info
            hist          = t.history(period="1y")
            current_price = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
            change        = clean_float(info.get("regularMarketChange"))
            change_pct    = clean_float(info.get("regularMarketChangePercent"))
            company_name  = info.get("longName") or info.get("shortName") or ticker
            sector        = info.get("sector") or "Unknown"
            market_value  = clean_float(pos.shares * current_price) if current_price else None
            cost_basis    = clean_float(pos.shares * pos.avg_cost)
            pnl_dollar    = clean_float(market_value - cost_basis) if market_value is not None else None
            pnl_pct       = clean_float(pnl_dollar / cost_basis * 100) if (pnl_dollar is not None and cost_basis and cost_basis != 0) else None
            day_chg_dollar= clean_float(pos.shares * change) if change is not None else None

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
                    logger.warning("Beta calc failed for %s", ticker, exc_info=True)

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
            logger.warning("Position fetch failed for %s", ticker, exc_info=True)
            position_data.append({
                "ticker": ticker, "company_name": ticker, "sector": "Unknown",
                "shares": pos.shares, "avg_cost": pos.avg_cost,
                "current_price": None, "market_value": None,
                "cost_basis": clean_float(pos.shares * pos.avg_cost),
                "pnl_dollar": None, "pnl_pct": None,
                "day_change_dollar": None, "day_change_pct": None,
                "beta": None, "weight": None,
            })

    total_mv  = sum(p["market_value"] for p in position_data if p["market_value"])
    total_cb  = sum(p["cost_basis"]   for p in position_data if p["cost_basis"])
    total_pnl = clean_float(total_mv - total_cb) if (total_mv and total_cb) else None
    total_pnl_pct = clean_float(total_pnl / total_cb * 100) if (total_pnl and total_cb and total_cb != 0) else None
    total_day = sum(p["day_change_dollar"] for p in position_data if p["day_change_dollar"])
    prev_mv   = (total_mv - total_day) if (total_mv and total_day) else None
    total_day_pct = clean_float(total_day / prev_mv * 100) if (total_day and prev_mv and prev_mv != 0) else None

    for p in position_data:
        if p["market_value"] and total_mv and total_mv > 0:
            p["weight"] = clean_float(p["market_value"] / total_mv * 100)

    sector_weights: dict = {}
    for p in position_data:
        s = p["sector"] or "Unknown"
        sector_weights[s] = sector_weights.get(s, 0) + (p["weight"] or 0)

    concentration_flags = [p["ticker"] for p in position_data if p["weight"] and p["weight"] > 20]

    portfolio_beta = None
    valid_betas    = [p for p in position_data if p["beta"] is not None and p["weight"] is not None]
    if valid_betas:
        portfolio_beta = clean_float(sum(p["weight"] / 100 * p["beta"] for p in valid_betas))

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
                    wa       = np.array(wts); wa = wa / wa.sum()
                    port_ret = combined.values @ wa
                    port_ret_series = pd.Series(port_ret, index=combined.index)
                    log_ret  = np.log(1 + port_ret_series).dropna()
                    if len(log_ret) >= 30:
                        portfolio_hv30d = clean_float(float(log_ret.tail(30).std() * math.sqrt(252) * 100))
                    if portfolio_hv30d and portfolio_hv30d > 0:
                        ann_ret = float((1 + port_ret_series.mean()) ** 252 - 1) * 100
                        sharpe  = clean_float((ann_ret - 5.0) / portfolio_hv30d)
                    cum          = (1 + port_ret_series).cumprod()
                    rmax         = cum.cummax()
                    max_drawdown = clean_float(float(((cum - rmax) / rmax).min()) * 100)
        except Exception:
            logger.warning("Portfolio risk metrics failed", exc_info=True)

    correlation_matrix = None
    if len(hist_map) >= 2:
        try:
            ret_dict = {tk: hist_map[tk].pct_change() for tk in hist_map}
            comb     = pd.concat(list(ret_dict.values()), axis=1, join="inner")
            comb.columns = list(ret_dict.keys())
            comb     = comb.dropna()
            corr     = comb.corr()
            correlation_matrix = {
                "tickers": list(corr.columns),
                "values":  [[clean_float(v) for v in row] for row in corr.values.tolist()],
            }
        except Exception:
            logger.warning("Correlation matrix failed", exc_info=True)

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
                    spy_norm   = spy_al / spy_al.dropna().iloc[-1] * total_mv
                    spy_prices = [round(float(v), 2) if not math.isnan(float(v)) else None for v in spy_norm.values]
            chart_data = {"dates": dates, "portfolio": prices, "spy": spy_prices}
        except Exception:
            logger.warning("Portfolio chart failed", exc_info=True)

    response = {
        "positions": position_data,
        "totals": {
            "market_value": total_mv, "cost_basis": total_cb,
            "pnl_dollar": total_pnl, "pnl_pct": total_pnl_pct,
            "day_change_dollar": total_day if total_day else None,
            "day_change_pct":    total_day_pct,
        },
        "metrics": {
            "total_value": total_mv, "beta": portfolio_beta,
            "hv30d": portfolio_hv30d, "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "num_positions": len(position_data),
            "concentration_flags": concentration_flags,
        },
        "sectors":     sector_weights,
        "correlation": correlation_matrix,
        "chart":       chart_data,
    }
    return deep_clean(response)
