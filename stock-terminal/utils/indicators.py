import numpy as np
import pandas as pd


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast    = calc_ema(close, fast)
    ema_slow    = calc_ema(close, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram   = macd_line - signal_line
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
    row        = rec_df.iloc[0]
    strong_buy = int(row.get("strongBuy",  0) or 0)
    buy        = int(row.get("buy",        0) or 0)
    hold       = int(row.get("hold",       0) or 0)
    sell       = int(row.get("sell",       0) or 0)
    strong_sell= int(row.get("strongSell", 0) or 0)
    total      = strong_buy + buy + hold + sell + strong_sell
    if total == 0:
        return empty
    total_buy  = strong_buy + buy
    total_sell = strong_sell + sell
    buy_pct    = total_buy  / total
    sell_pct   = total_sell / total
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


def montecarlo_portfolio(
    returns_df,
    weights: dict,
    n_sims: int = 1000,
    n_days: int = 252,
    portfolio_value: float = 10_000,
) -> dict:
    """
    Correlated GBM Monte Carlo simulation for a multi-asset portfolio.

    returns_df : pd.DataFrame — daily returns, columns = ticker symbols
    weights    : dict {ticker: fraction} — renormalized internally
    """
    tickers = [t for t in returns_df.columns if t in weights]
    if not tickers:
        return {}
    df = returns_df[tickers].dropna()
    if len(df) < 30:
        return {}

    w = np.array([weights[t] for t in tickers], dtype=float)
    w /= w.sum()

    mu  = df.mean().to_numpy()
    cov = df.cov().to_numpy() + np.eye(len(tickers)) * 1e-8
    L   = np.linalg.cholesky(cov)

    paths = np.empty((n_sims, n_days + 1))
    paths[:, 0] = portfolio_value

    rng = np.random.default_rng()
    for d in range(1, n_days + 1):
        Z      = rng.standard_normal((len(tickers), n_sims))
        r      = mu[:, None] + L @ Z          # correlated per-asset daily returns
        port_r = (w[:, None] * r).sum(axis=0) # weighted portfolio daily return
        paths[:, d] = paths[:, d - 1] * (1 + port_r)

    pcts  = np.percentile(paths, [5, 25, 50, 75, 95], axis=0)
    final = paths[:, -1]

    return {
        "days":          n_days,
        "initial_value": round(float(portfolio_value), 2),
        "paths": {
            "p5":  [round(float(v), 2) for v in pcts[0]],
            "p25": [round(float(v), 2) for v in pcts[1]],
            "p50": [round(float(v), 2) for v in pcts[2]],
            "p75": [round(float(v), 2) for v in pcts[3]],
            "p95": [round(float(v), 2) for v in pcts[4]],
        },
        "stats": {
            "expected_return": round(float(np.mean(final) / portfolio_value - 1) * 100, 2),
            "var95":           round(float(np.percentile(final, 5) / portfolio_value - 1) * 100, 2),
            "prob_gain":       round(float(np.mean(final > portfolio_value)) * 100, 1),
            "median_final":    round(float(np.median(final)), 2),
            "p95_final":       round(float(np.percentile(final, 95)), 2),
            "p5_final":        round(float(np.percentile(final, 5)), 2),
        },
    }
