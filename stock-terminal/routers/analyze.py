import json
import math
from typing import Optional, AsyncGenerator

import pandas as pd
import yfinance as yf
import anthropic

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from jose import JWTError

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, logger
from services.supabase_auth import verify_supabase_jwt
from utils.market_data import clean_float
from utils.indicators import calc_rsi

router = APIRouter()


@router.get("/analyze/{symbol}")
async def analyze_ticker(symbol: str, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to use AI Analysis")
    try:
        verify_supabase_jwt(authorization.split(" ", 1)[1])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    symbol = symbol.upper().strip()

    try:
        tk   = yf.Ticker(symbol)
        info = tk.info or {}

        price        = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        prev_close   = clean_float(info.get("previousClose"))
        change_pct   = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else None
        mkt_cap      = info.get("marketCap")
        pe           = clean_float(info.get("trailingPE"))
        fwd_pe       = clean_float(info.get("forwardPE"))
        eps          = clean_float(info.get("trailingEps"))
        rev_growth   = clean_float(info.get("revenueGrowth"))
        earn_growth  = clean_float(info.get("earningsGrowth"))
        gross_margin = clean_float(info.get("grossMargins"))
        profit_margin= clean_float(info.get("profitMargins"))
        debt_equity  = clean_float(info.get("debtToEquity"))
        roe          = clean_float(info.get("returnOnEquity"))
        beta         = clean_float(info.get("beta"))
        target_price = clean_float(info.get("targetMeanPrice"))
        rec          = info.get("recommendationKey", "")
        sector       = info.get("sector", "")
        industry     = info.get("industry", "")
        company_name = info.get("longName", symbol)
        wk52_hi      = clean_float(info.get("fiftyTwoWeekHigh"))
        wk52_lo      = clean_float(info.get("fiftyTwoWeekLow"))

        hist    = tk.history(period="90d", interval="1d")
        rsi_val = None
        sma50   = None
        sma200  = None

        if not hist.empty and len(hist) > 14:
            close      = hist["Close"]
            rsi_series = calc_rsi(close)
            rsi_val    = round(float(rsi_series.iloc[-1]), 1) if not pd.isna(rsi_series.iloc[-1]) else None
            if len(close) >= 50:
                sma50  = round(float(close.rolling(50).mean().iloc[-1]), 2)
            if len(close) >= 200:
                sma200 = round(float(close.rolling(200).mean().iloc[-1]), 2)

    except Exception as e:
        logger.error("AI analysis data fetch failed for %s", symbol, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {e}")

    def fmt(v, prefix="", suffix="", decimals=2):
        if v is None: return "N/A"
        return f"{prefix}{v:,.{decimals}f}{suffix}"

    def fmt_pct(v):
        if v is None: return "N/A"
        return f"{'+' if v >= 0 else ''}{v:.1f}%"

    def fmt_cap(v):
        if v is None: return "N/A"
        if v >= 1e12: return f"${v/1e12:.2f}T"
        if v >= 1e9:  return f"${v/1e9:.1f}B"
        return f"${v/1e6:.0f}M"

    prompt = f"""You are a sharp, concise equity analyst. Analyze {company_name} ({symbol}) based on the following real-time data and give a structured assessment. Be direct, specific, and insightful — no generic disclaimers.

## Market Data (live)
- Price: {fmt(price, '$')}  |  Change today: {fmt_pct(change_pct)}
- Market Cap: {fmt_cap(mkt_cap)}
- Beta: {fmt(beta, decimals=2)}
- 52-Week Range: {fmt(wk52_lo, '$')} – {fmt(wk52_hi, '$')}
- Sector: {sector}  |  Industry: {industry}

## Valuation
- Trailing P/E: {fmt(pe, decimals=1)}x
- Forward P/E: {fmt(fwd_pe, decimals=1)}x
- EPS (TTM): {fmt(eps, '$')}
- Analyst Target Price: {fmt(target_price, '$')}  |  Consensus: {rec.upper() if rec else 'N/A'}

## Fundamentals
- Revenue Growth (YoY): {fmt_pct(rev_growth * 100) if rev_growth else 'N/A'}
- Earnings Growth (YoY): {fmt_pct(earn_growth * 100) if earn_growth else 'N/A'}
- Gross Margin: {fmt_pct(gross_margin * 100) if gross_margin else 'N/A'}
- Net Profit Margin: {fmt_pct(profit_margin * 100) if profit_margin else 'N/A'}
- Return on Equity: {fmt_pct(roe * 100) if roe else 'N/A'}
- Debt/Equity: {fmt(debt_equity, decimals=1)}x

## Technical Picture
- RSI (14d): {fmt(rsi_val, decimals=1)}
- 50-Day SMA: {fmt(sma50, '$')}  |  Price vs 50d: {f"{'+' if price and sma50 and price > sma50 else '-'}{abs(price - sma50) / sma50 * 100:.1f}%" if price and sma50 else 'N/A'}
- 200-Day SMA: {fmt(sma200, '$')}  |  Price vs 200d: {f"{'+' if price and sma200 and price > sma200 else '-'}{abs(price - sma200) / sma200 * 100:.1f}%" if price and sma200 else 'N/A'}

## Your Analysis

Write a structured analysis with exactly these four sections. Use markdown headers (##). Be specific and reference the actual numbers above:

## Snapshot
2-3 sentences on what this company does and where it stands right now. Mention price action and sentiment.

## Bull Case
3 specific reasons to be bullish, grounded in the data above. Reference actual metrics.

## Bear Case
3 specific risks or red flags from the data. Be honest about weaknesses.

## Verdict
A clear, opinionated 2-3 sentence summary. Include: current bias (bullish/bearish/neutral), key level to watch, and one actionable insight. End with a price target range if data supports it.

Keep the total response under 400 words. No disclaimers."""

    async def event_stream() -> AsyncGenerator[str, None]:
        if not ANTHROPIC_API_KEY:
            yield f"data: {json.dumps({'error': 'ANTHROPIC_API_KEY not configured. Add it to your .env file or Railway environment variables.'})}\n\n"
            return
        try:
            ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            with ai_client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("AI analysis stream failed for %s", symbol, exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
