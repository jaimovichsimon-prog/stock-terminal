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
