from pathlib import Path
import math
import datetime
import os
import json
import time
import re
from typing import List, Optional, AsyncGenerator

# Load .env file if present (local dev)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

import hashlib
import secrets
import base64
import smtplib
import threading
from email.mime.text import MIMEText

from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import yfinance as yf
import feedparser
import anthropic
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

# Auth deps
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, func, select, delete as sa_delete
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from jose import JWTError, jwt

app = FastAPI(title="Stock Terminal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INDEX_HTML = Path(__file__).parent / "index.html"

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
# Use /app/data on Railway (persistent volume) or local dir in dev
_data_dir = Path(os.environ.get("DB_DIR", str(Path(__file__).parent)))
_data_dir.mkdir(parents=True, exist_ok=True)
DB_PATH = _data_dir / "terminal.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id         = Column(Integer, primary_key=True, index=True)
    email      = Column(String, unique=True, index=True, nullable=False)
    hashed_pw  = Column(String, nullable=False)
    created_at = Column(DateTime, default=func.now())

class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"
    id       = Column(Integer, primary_key=True, index=True)
    user_id  = Column(Integer, nullable=False, index=True)
    ticker   = Column(String, nullable=False)
    shares   = Column(Float, nullable=False)
    avg_cost = Column(Float, nullable=False)

class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    id      = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    ticker  = Column(String, nullable=False)

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, nullable=False, index=True)
    token      = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used       = Column(Integer, default=0)

class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, nullable=False, index=True)
    ticker       = Column(String, nullable=False)
    condition    = Column(String, nullable=False)  # 'above' | 'below'
    target_price = Column(Float, nullable=False)
    triggered    = Column(Integer, default=0)
    created_at   = Column(DateTime, default=func.now())

class Transaction(Base):
    __tablename__ = "transactions"
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, nullable=False, index=True)
    ticker     = Column(String, nullable=False)
    tx_type    = Column(String, nullable=False)   # 'buy' | 'sell'
    shares     = Column(Float, nullable=False)
    price      = Column(Float, nullable=False)
    date       = Column(String, nullable=False)   # YYYY-MM-DD
    notes      = Column(String, default='')
    created_at = Column(DateTime, default=func.now())

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Auth utilities
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Email notification (new user sign-up)
# ---------------------------------------------------------------------------
_NOTIFY_EMAIL  = os.environ.get("NOTIFY_EMAIL", "jaimovichsimon@gmail.com")
_SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
_SMTP_USER     = os.environ.get("SMTP_USER", "")
_SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

def _send_signup_email(new_user_email: str):
    """Fire-and-forget email — runs in a background thread so it never blocks the response."""
    if not _SMTP_USER or not _SMTP_PASSWORD:
        return  # SMTP not configured, skip silently
    try:
        msg = MIMEText(
            f"New user registered on Stock Terminal:\n\n"
            f"  Email: {new_user_email}\n"
            f"  Time:  {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n",
            "plain"
        )
        msg["Subject"] = f"[Stock Terminal] New sign-up: {new_user_email}"
        msg["From"]    = _SMTP_USER
        msg["To"]      = _NOTIFY_EMAIL
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(_SMTP_USER, _SMTP_PASSWORD)
            smtp.sendmail(_SMTP_USER, [_NOTIFY_EMAIL], msg.as_string())
    except Exception:
        pass  # never break registration if email fails

def notify_new_user(email: str):
    threading.Thread(target=_send_signup_email, args=(email,), daemon=True).start()

_APP_URL = os.environ.get("APP_URL", "http://localhost:8000")

def _send_reset_email(to_email: str, token: str):
    if not _SMTP_USER or not _SMTP_PASSWORD:
        return
    try:
        reset_url = f"{_APP_URL}/?action=reset&token={token}"
        msg = MIMEText(
            f"Someone requested a password reset for your Terminal Pro account.\n\n"
            f"Click the link below to set a new password (valid for 1 hour):\n\n"
            f"{reset_url}\n\n"
            f"If you didn't request this, you can ignore this email.\n",
            "plain"
        )
        msg["Subject"] = "[Terminal Pro] Password Reset"
        msg["From"]    = _SMTP_USER
        msg["To"]      = to_email
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(_SMTP_USER, _SMTP_PASSWORD)
            smtp.sendmail(_SMTP_USER, [to_email], msg.as_string())
    except Exception:
        pass

def _send_alert_email(to_email: str, ticker: str, condition: str, target: float, current: float):
    if not _SMTP_USER or not _SMTP_PASSWORD:
        return
    try:
        direction = "above" if condition == "above" else "below"
        msg = MIMEText(
            f"Price alert triggered for {ticker}:\n\n"
            f"  Your alert:    price {direction} ${target:,.2f}\n"
            f"  Current price: ${current:,.2f}\n"
            f"  Time: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
            f"Log in to Terminal Pro to view your positions.\n",
            "plain"
        )
        msg["Subject"] = f"[Terminal Pro] Alert: {ticker} is {direction} ${target:,.2f}"
        msg["From"]    = _SMTP_USER
        msg["To"]      = to_email
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(_SMTP_USER, _SMTP_PASSWORD)
            smtp.sendmail(_SMTP_USER, [to_email], msg.as_string())
    except Exception:
        pass

def _run_alert_checks():
    db = SessionLocal()
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
                pass
        for alert in alerts:
            price = prices.get(alert.ticker)
            if price is None:
                continue
            hit = (alert.condition == "above" and price >= alert.target_price) or \
                  (alert.condition == "below" and price <= alert.target_price)
            if hit:
                alert.triggered = 1
                db.commit()
                user = db.execute(select(User).where(User.id == alert.user_id)).scalar_one_or_none()
                if user:
                    threading.Thread(
                        target=_send_alert_email,
                        args=(user.email, alert.ticker, alert.condition, alert.target_price, price),
                        daemon=True,
                    ).start()
    except Exception:
        pass
    finally:
        db.close()

def _alert_loop():
    while True:
        time.sleep(300)
        try:
            _run_alert_checks()
        except Exception:
            pass

threading.Thread(target=_alert_loop, daemon=True).start()

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production-please")
JWT_ALG    = "HS256"
JWT_EXPIRE = 60 * 24 * 30  # 30 days in minutes

_PBKDF2_ITERS = 260_000

def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), _PBKDF2_ITERS)
    return f"{salt}${base64.b64encode(dk).decode()}"

def verify_password(pw: str, hashed: str) -> bool:
    try:
        salt, stored = hashed.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), _PBKDF2_ITERS)
        return base64.b64encode(dk).decode() == stored
    except Exception:
        return False

def create_token(user_id: int, email: str) -> str:
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=JWT_EXPIRE)
    return jwt.encode({"sub": str(user_id), "email": email, "exp": expire}, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])

def get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(authorization.split(" ", 1)[1])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# ---------------------------------------------------------------------------
# Auth Pydantic models
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    token: str
    email: str
    user_id: int

# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@app.post("/api/auth/register", response_model=AuthResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    body.email = body.email.strip().lower()
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if db.execute(select(User).where(User.email == body.email)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=body.email, hashed_pw=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    notify_new_user(user.email)   # ← email notification, non-blocking
    return AuthResponse(token=create_token(user.id, user.email), email=user.email, user_id=user.id)

@app.post("/api/auth/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    body.email = body.email.strip().lower()
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_pw):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return AuthResponse(token=create_token(user.id, user.email), email=user.email, user_id=user.id)

@app.get("/api/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {"user_id": current_user.id, "email": current_user.email}

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@app.post("/api/auth/forgot-password")
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user:
        db.execute(sa_delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        token = secrets.token_urlsafe(32)
        expires = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        db.add(PasswordResetToken(user_id=user.id, token=token, expires_at=expires))
        db.commit()
        threading.Thread(target=_send_reset_email, args=(user.email, token), daemon=True).start()
    return {"ok": True}  # always ok — prevents email enumeration

@app.post("/api/auth/reset-password", response_model=AuthResponse)
def reset_password_endpoint(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(body.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    rt = db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == body.token,
            PasswordResetToken.used == 0,
        )
    ).scalar_one_or_none()
    if not rt or rt.expires_at < datetime.datetime.utcnow():
        raise HTTPException(400, "Reset link is invalid or has expired")
    user = db.execute(select(User).where(User.id == rt.user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(400, "User not found")
    user.hashed_pw = hash_password(body.new_password)
    rt.used = 1
    db.commit()
    return AuthResponse(token=create_token(user.id, user.email), email=user.email, user_id=user.id)

# ---------------------------------------------------------------------------
# User data models
# ---------------------------------------------------------------------------
class PositionItem(BaseModel):
    ticker:   str
    shares:   float
    avg_cost: float

class PortfolioBody(BaseModel):
    positions: List[PositionItem]

class WatchlistBody(BaseModel):
    tickers: List[str]

class AlertBody(BaseModel):
    ticker: str
    condition: str   # 'above' | 'below'
    target_price: float

class TransactionBody(BaseModel):
    ticker:  str
    tx_type: str     # 'buy' | 'sell'
    shares:  float
    price:   float
    date:    str     # YYYY-MM-DD
    notes:   str = ''

# ---------------------------------------------------------------------------
# Portfolio endpoints
# ---------------------------------------------------------------------------
@app.get("/api/user/portfolio")
def get_portfolio(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(PortfolioPosition).where(PortfolioPosition.user_id == current_user.id)
    ).scalars().all()
    return {"positions": [{"ticker": r.ticker, "shares": r.shares, "avg_cost": r.avg_cost} for r in rows]}

@app.put("/api/user/portfolio")
def put_portfolio(body: PortfolioBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(sa_delete(PortfolioPosition).where(PortfolioPosition.user_id == current_user.id))
    for p in body.positions:
        db.add(PortfolioPosition(
            user_id=current_user.id,
            ticker=p.ticker.upper().strip(),
            shares=p.shares,
            avg_cost=p.avg_cost,
        ))
    db.commit()
    return {"ok": True, "count": len(body.positions)}

# ---------------------------------------------------------------------------
# Watchlist endpoints
# ---------------------------------------------------------------------------
@app.get("/api/user/watchlist")
def get_watchlist(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == current_user.id)
    ).scalars().all()
    return {"tickers": [r.ticker for r in rows]}

@app.put("/api/user/watchlist")
def put_watchlist(body: WatchlistBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(sa_delete(WatchlistItem).where(WatchlistItem.user_id == current_user.id))
    seen = set()
    for t in body.tickers:
        t = t.upper().strip()
        if t and t not in seen:
            db.add(WatchlistItem(user_id=current_user.id, ticker=t))
            seen.add(t)
    db.commit()
    return {"ok": True, "count": len(seen)}


@app.get("/api/user/alerts")
def get_alerts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(PriceAlert).where(PriceAlert.user_id == current_user.id)
    ).scalars().all()
    return {"alerts": [
        {"id": r.id, "ticker": r.ticker, "condition": r.condition,
         "target_price": r.target_price, "triggered": bool(r.triggered),
         "created_at": str(r.created_at)} for r in rows
    ]}

@app.post("/api/user/alerts")
def create_alert(body: AlertBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.condition not in ("above", "below"):
        raise HTTPException(400, "condition must be 'above' or 'below'")
    db.add(PriceAlert(
        user_id=current_user.id,
        ticker=body.ticker.upper().strip(),
        condition=body.condition,
        target_price=body.target_price,
    ))
    db.commit()
    return {"ok": True}

@app.delete("/api/user/alerts/{alert_id}")
def delete_alert(alert_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(
        sa_delete(PriceAlert).where(
            PriceAlert.id == alert_id,
            PriceAlert.user_id == current_user.id,
        )
    )
    db.commit()
    return {"ok": True}

@app.get("/api/user/transactions")
def get_transactions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Transaction).where(Transaction.user_id == current_user.id)
    ).scalars().all()
    txs = [
        {"id": r.id, "ticker": r.ticker, "tx_type": r.tx_type,
         "shares": r.shares, "price": r.price, "date": r.date, "notes": r.notes}
        for r in sorted(rows, key=lambda x: x.date, reverse=True)
    ]
    return {"transactions": txs}

@app.post("/api/user/transactions")
def add_transaction(body: TransactionBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.tx_type not in ("buy", "sell"):
        raise HTTPException(400, "tx_type must be 'buy' or 'sell'")
    db.add(Transaction(
        user_id=current_user.id,
        ticker=body.ticker.upper().strip(),
        tx_type=body.tx_type,
        shares=body.shares,
        price=body.price,
        date=body.date,
        notes=body.notes,
    ))
    db.commit()
    return {"ok": True}

@app.delete("/api/user/transactions/{tx_id}")
def delete_transaction(tx_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(
        sa_delete(Transaction).where(
            Transaction.id == tx_id,
            Transaction.user_id == current_user.id,
        )
    )
    db.commit()
    return {"ok": True}

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

class PortfolioPositionIn(BaseModel):
    ticker: str
    shares: float
    avg_cost: float

class PortfolioRequest(BaseModel):
    positions: List[PortfolioPositionIn]


@app.post("/api/portfolio")
def get_portfolio_analysis(req: PortfolioRequest):
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
    # Central banks — highest signal
    ("Federal Reserve",       "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ECB",                   "https://www.ecb.europa.eu/rss/fsr.xml"),
    # Tier-1 wire services
    ("Reuters Business",      "https://feeds.reuters.com/reuters/businessNews"),
    ("Reuters Markets",       "https://feeds.reuters.com/reuters/financeNews"),
    ("AP Business",           "https://apnews.com/hub/business.rss"),
    # Major financial media
    ("CNBC Markets",          "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("CNBC Economy",          "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    ("MarketWatch",           "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("Barrons",               "https://www.barrons.com/xml/rss/3_7514.xml"),
    ("Investing.com",         "https://www.investing.com/rss/news_301.rss"),
    # Quality general
    ("Yahoo Finance",         "https://finance.yahoo.com/news/rssindex"),
    ("The Economist Finance", "https://www.economist.com/finance-and-economics/rss.xml"),
    ("NPR Business",          "https://feeds.npr.org/1006/rss.xml"),
    ("BBC Business",          "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("The Guardian Business", "https://www.theguardian.com/business/rss"),
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


_EXCLUDE_KEYWORDS = [
    "nfl", "nba", "nhl", "mlb", "soccer", "cricket", "rugby", "tennis", "golf",
    "celebrity", "fashion", "lifestyle", "recipe", "travel", "tourism",
    "movie", "film", "music", "entertainment", "oscars", "grammy",
    "horoscope", "crossword", "puzzle",
    "podcast", "interview", "opinion", "column", "newsletter",
    "webinar", "survey", "poll", "quiz", "listicle", "explainer",
]

_CAT_KEYWORDS = {
    "Fed/Monetary Policy": [
        "federal reserve", "fed", "fomc", "interest rate", "rate hike", "rate cut",
        "central bank", "ecb", "bank of england", "boe", "boj", "bank of japan",
        "quantitative easing", "quantitative tightening", "monetary policy",
        "inflation", "cpi", "pce", "price stability", "jerome powell", "powell",
        "lagarde", "rate decision", "rate hold", "fed meeting", "fed statement",
        "fed minutes", "beige book", "press conference", "dot plot",
        "fed chair", "fed governor", "fed president",
        "fed funds rate", "neutral rate", "r-star", "terminal rate",
        "balance sheet", "reverse repo", "treasury purchases", "yield curve",
        "2yr", "10yr", "30yr", "hawkish", "dovish", "tightening", "easing",
    ],
    "Geopolitics": [
        "war", "conflict", "military", "sanctions", "sanction", "geopolit",
        "nato", "ukraine", "russia", "iran", "middle east", "taiwan",
        "north korea", "missile", "troops", "invasion", "ceasefire", "treaty",
        "diplomat", "embassy", "nuclear",
    ],
    "Commodities": [
        "oil price", "crude oil", "opec", "natural gas", "energy price",
        "commodity", "gold price", "silver", "wheat", "corn", "supply chain",
        "strait of hormuz", "brent", "wti", "lng",
    ],
    "Tech/AI": [
        "artificial intelligence", " ai ", "openai", "nvidia", "chip shortage",
        "semiconductor", "antitrust", "big tech", "regulation tech",
        "chatgpt", "machine learning", "data center", "cloud computing",
    ],
    "Markets": [
        "stock market", "wall street", "s&p 500", "nasdaq", "dow jones",
        "treasury yield", "bond yield", "credit market", "hedge fund",
        "market rally", "market selloff", "market crash", "volatility",
        "dollar index", "currency", "forex", "ipo",
    ],
    "Macro Economy": [
        "gdp", "recession", "unemployment", "jobs report", "nonfarm payroll",
        "trade deficit", "trade war", "tariff", "fiscal policy", "budget deficit",
        "national debt", "economic growth", "consumer confidence",
        "manufacturing", "pmi", "retail sales",
    ],
}

# Any article containing at least one of these gets through automatically
_HIGH_IMPORTANCE = [
    "federal reserve", "fomc", "rate decision", "rate hike", "rate cut",
    "fed holds", "fed raises", "fed cuts", "fed pauses",
    "powell speaks", "powell said", "jerome powell",
    "fed statement", "fed minutes", "fed meeting", "press conference",
    "inflation data", "cpi report", "jobs report", "nonfarm payroll",
    "gdp growth", "gdp contraction", "recession",
    "war ", "invasion", "military strike", "nuclear",
    "sanctions", "opec", "oil supply", "oil price",
    "market crash", "stock market crash", "financial crisis",
    "bank collapse", "bank failure", "systemic",
    "tariff", "trade war",
    "artificial intelligence regulation", "ai regulation",
    "yield curve inversion", "hawkish", "dovish", "rate unchanged",
    "basis points", "bps", "emergency meeting", "systemic risk",
    "contagion", "bank run", "credit crunch", "debt ceiling",
    "sovereign default", "currency crisis", "flash crash",
]

# ---------------------------------------------------------------------------
# Sentiment classification — equity/risk-asset perspective, phrase-weighted
# ---------------------------------------------------------------------------
# Multi-word phrases are scored ±2 (more precise context).
# Single words use padded spaces for boundary matching and score ±1.
# Net score must reach ±2 to avoid mis-classifying from a single weak word.
# Words like "cut", "fall", "risk", "concern" are intentionally omitted:
# they are too ambiguous on their own (rate CUT = Positive for equities).

_SENT_PHRASES_POS = [  # score +2 each
    "rate cut", "rate cuts", "fed cut", "fed cuts", "fed pivot", "fed pause",
    "fed pauses", "interest rate cut", "interest rate cuts",
    "better than expected", "beat expectations", "beats estimates",
    "beat estimates", "above expectations", "strong jobs report",
    "blowout quarter", "record high", "all-time high", "new all-time high",
    "soft landing", "dovish", "dovish signal", "easing cycle",
    "quantitative easing", "stimulus package", "fiscal stimulus",
    "ceasefire", "peace deal", "trade deal", "trade agreement signed",
    "inflation cools", "cooling inflation", "lower inflation",
    "disinflation", "inflation slows", "inflation falls",
    "market rally", "stocks rally", "equities rally", "stocks surge",
    "strong gdp", "gdp beats", "economy accelerates", "upgrade",
    "raised guidance", "raised outlook", "buyback", "dividend increase",
]

_SENT_PHRASES_NEG = [  # score -2 each
    "rate hike", "rate hikes", "interest rate hike", "interest rate hikes",
    "hawkish", "hawkish signal", "tightening cycle", "emergency rate hike",
    "worse than expected", "miss expectations", "misses estimates",
    "missed estimates", "below expectations", "disappoints",
    "market crash", "flash crash", "market sell-off", "market selloff",
    "stocks plunge", "equities fall sharply",
    "bank collapse", "bank failure", "bank run", "systemic risk",
    "financial crisis", "credit crunch", "contagion",
    "stagflation", "hyperinflation", "inflation surge", "inflation spike",
    "inflation jumps", "inflation accelerates",
    "recession confirmed", "gdp contraction", "gdp shrinks",
    "yield curve inversion", "sovereign default", "debt ceiling crisis",
    "credit downgrade", "rating downgrade", "emergency meeting",
    "war escalates", "military invasion", "military strike",
    "nuclear threat", "sanctions imposed", "oil supply disruption",
    "tariff escalation", "trade war escalates",
    "mass layoffs", "layoffs announced", "job cuts announced",
]

_SENT_WORDS_POS = [  # score +1 each (word-boundary matched)
    " rally ", " rallies ", " surge ", " surges ", " gain ", " gains ",
    " rise ", " rises ", " jump ", " jumps ", " soar ", " soars ",
    " boom ", " recovery ", " recovers ", " rebound ", " rebounds ",
    " bullish ", " upbeat ", " optimism ", " expansion ", " expansionary ",
    " hiring ", " outperform ", " outperforms ", " upgrade ", " upgrades ",
    " improves ", " improvement ",
]

_SENT_WORDS_NEG = [  # score -1 each (word-boundary matched)
    " crash ", " crashes ", " collapse ", " collapses ",
    " plunge ", " plunges ", " tumble ", " tumbles ",
    " slump ", " slumps ", " bearish ", " slowdown ",
    " downturn ", " layoffs ", " contraction ", " recessionary ",
    " downgrade ", " downgrades ", " underperform ",
]


def _classify_category(text: str) -> str:
    # Strong Fed signals override scoring
    fed_triggers = ["federal reserve", "fomc", "powell", "fed meeting", "rate decision",
                    "rate hike", "rate cut", "fed statement", "fed holds", "press conference"]
    if any(kw in text for kw in fed_triggers):
        return "Fed/Monetary Policy"
    scores = {cat: sum(1 for kw in kws if kw in text) for cat, kws in _CAT_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Macro Economy"


def _classify_sentiment(text: str) -> str:
    """
    Classify market sentiment from equity-investor perspective.
    'Rate cut' = Positive (equities love it). 'Rate hike' = Negative.
    Net score >= +2 → Positive, <= -2 → Negative, else Neutral.
    """
    t = " " + text + " "   # pad for clean word-boundary matching
    score = 0
    for phrase in _SENT_PHRASES_POS:
        if phrase in t:
            score += 2
    for phrase in _SENT_PHRASES_NEG:
        if phrase in t:
            score -= 2
    for word in _SENT_WORDS_POS:
        if word in t:
            score += 1
    for word in _SENT_WORDS_NEG:
        if word in t:
            score -= 1
    if score >= 2:
        return "Positive"
    if score <= -2:
        return "Negative"
    return "Neutral"


def _keyword_filter(articles: list[dict]) -> list[dict]:
    """Fallback filter used when ANTHROPIC_API_KEY is not set."""
    results = []
    for a in articles:
        text = (a["title"] + " " + a["summary"]).lower()

        if any(kw in text for kw in _EXCLUDE_KEYWORDS):
            continue

        # High-importance trigger — always include, score 8-9
        high_hits = sum(1 for kw in _HIGH_IMPORTANCE if kw in text)

        # Category keyword hits for scoring
        cat_hits = sum(1 for kws in _CAT_KEYWORDS.values() for kw in kws if kw in text)

        # Always include any Fed/central bank article at score 8+
        is_fed = any(kw in text for kw in [
            "federal reserve", "fomc", "powell", "fed meeting",
            "rate decision", "rate hike", "rate cut", "fed statement",
            "ecb", "bank of england", "bank of japan", "central bank",
            "hawkish", "dovish", "basis points", "bps",
        ])
        if not is_fed and high_hits == 0 and cat_hits < 2:
            continue

        if is_fed:
            score = 8
            if high_hits >= 2:
                score = 9
        elif high_hits >= 2 or cat_hits >= 5:
            score = 9
        elif high_hits == 1 or cat_hits >= 3:
            score = 8
        elif cat_hits >= 5:
            score = 8
        else:
            score = 7

        category  = _classify_category(text)
        sentiment = _classify_sentiment(text)

        results.append({
            **a,
            "importance_score": score,
            "category":         category,
            "market_impact":    "",
            "sentiment":        sentiment,
        })

    results.sort(key=lambda x: x["importance_score"], reverse=True)
    return results[:25]


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
        "You are a financial news analyst for a professional equity trading terminal.\n"
        "Your job: filter macro-relevant news AND classify each article's sentiment "
        "strictly from the perspective of an equity investor (S&P 500 / risk assets).\n\n"
        "INCLUDE: Fed/central bank decisions, inflation data, jobs reports, GDP, "
        "geopolitical conflicts, oil/gas disruptions, wars, sanctions, AI regulation, "
        "systemic financial risk, sovereign events, major elections.\n"
        "EXCLUDE: individual company earnings (unless systemic), crypto minor moves, "
        "sports, lifestyle, celebrity, regional politics with no macro impact, "
        "routine data in-line with forecasts.\n\n"
        "SENTIMENT — always relative to equities / risk assets:\n"
        "  Positive = news that should LIFT equity prices or reduce risk premiums.\n"
        "    Rate cut / Fed pause / dovish signal → Positive\n"
        "    Inflation cooling / soft landing / strong jobs → Positive\n"
        "    Ceasefire / trade deal / stimulus → Positive\n"
        "    Better-than-expected economic data → Positive\n"
        "  Negative = news that should PRESSURE equity prices or widen risk premiums.\n"
        "    Rate hike / hawkish surprise / tightening → Negative\n"
        "    Inflation surge / stagflation fears → Negative\n"
        "    Bank failure / credit crunch / systemic risk → Negative\n"
        "    War escalation / sanctions / supply shock → Negative\n"
        "    Recession confirmed / GDP contraction → Negative\n"
        "  Neutral = genuinely ambiguous; equity impact unclear or mixed.\n"
        "    In-line data with no surprise, Fed hold with balanced tone → Neutral\n"
        "CRITICAL: Do NOT use the tone of the headline as a proxy. "
        "'Unemployment rises' can be Positive if it means the Fed will ease. "
        "'Fed pauses rate hikes' sounds neutral but is Positive for equities. "
        "Always reason from the actual equity market impact.\n\n"
        "Return a JSON array where each passing article has:\n"
        "  id (original index), importance_score (1-10), "
        "category (one of: Fed/Monetary Policy, Geopolitics, Commodities, Tech/AI, Markets, Macro Economy), "
        "market_impact (2 sentences for a trader), "
        "sentiment (exactly: Positive, Negative, or Neutral)\n"
        "Only include articles with importance_score >= 7.\n"
        "Return only valid JSON array. No markdown, no preamble."
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


@app.get("/api/news/ticker/{symbol}")
def get_ticker_news(symbol: str):
    symbol = symbol.upper().strip()
    try:
        tk = yf.Ticker(symbol)
        raw = tk.news or []
        articles = []
        for item in raw[:20]:
            pub_ts = item.get("providerPublishTime") or item.get("pubDate")
            pub_dt = None
            if pub_ts:
                try:
                    pub_dt = datetime.datetime.fromtimestamp(int(pub_ts), tz=datetime.timezone.utc).isoformat()
                except Exception:
                    pass
            articles.append({
                "title":        item.get("title", ""),
                "url":          item.get("link", "") or item.get("url", ""),
                "source":       item.get("publisher", "") or item.get("source", ""),
                "published_at": pub_dt,
                "summary":      item.get("summary", "")[:400],
            })
        return {"articles": articles, "ticker": symbol}
    except Exception:
        return {"articles": [], "ticker": symbol}

# ---------------------------------------------------------------------------
# Macro Dashboard endpoint
# ---------------------------------------------------------------------------

MACRO_TICKERS = {
    "S&P 500":  "^GSPC",
    "Nasdaq":   "^IXIC",
    "VIX":      "^VIX",
    "10Y Yield":"^TNX",
    "DXY":      "DX-Y.NYB",
    "WTI Oil":  "CL=F",
    "Gold":     "GC=F",
    "BTC":      "BTC-USD",
}

_macro_cache: dict = {"ts": 0.0, "data": None}
MACRO_CACHE_TTL = 60


@app.get("/api/macro")
def get_macro():
    now = time.time()
    if _macro_cache["data"] is not None and (now - _macro_cache["ts"]) < MACRO_CACHE_TTL:
        return _macro_cache["data"]

    indicators = []
    for name, sym in MACRO_TICKERS.items():
        try:
            info = yf.Ticker(sym).info
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
            indicators.append({"name": name, "ticker": sym,
                               "price": None, "change": None,
                               "change_pct": None, "prev_close": None})

    result = deep_clean({"indicators": indicators})
    _macro_cache["ts"]   = now
    _macro_cache["data"] = result
    return result


# ---------------------------------------------------------------------------
# Watchlist endpoint
# ---------------------------------------------------------------------------

@app.get("/api/watchlist")
def get_watchlist(tickers: str = ""):
    if not tickers.strip():
        return {"positions": []}

    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()][:30]
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
            results.append({"ticker": sym, "company_name": sym,
                            "sector": None, "current_price": None,
                            "change": None, "change_pct": None,
                            "market_cap": None, "pe_trailing": None,
                            "volume": None, "day_high": None,
                            "day_low": None, "week52_high": None, "week52_low": None})

    return deep_clean({"positions": results})


# ---------------------------------------------------------------------------
# Earnings Calendar endpoint
# ---------------------------------------------------------------------------

@app.get("/api/earnings")
def get_earnings(tickers: str = ""):
    if not tickers.strip():
        return {"earnings": []}

    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()][:20]
    results = []
    today = datetime.date.today()

    for sym in syms:
        try:
            t = yf.Ticker(sym)
            info = t.info
            company = info.get("longName") or info.get("shortName") or sym

            # Try earnings_dates DataFrame first (most reliable)
            try:
                ed = t.earnings_dates
                if ed is not None and not ed.empty:
                    # Filter to future dates within 90 days
                    future = ed[ed.index >= pd.Timestamp(today, tz="America/New_York")]
                    if not future.empty:
                        row = future.iloc[-1]  # earliest upcoming
                        eps_est = clean_float(row.get("EPS Estimate"))
                        eps_act = clean_float(row.get("Reported EPS"))
                        results.append({
                            "ticker":        sym,
                            "company_name":  company,
                            "earnings_date": future.index[-1].strftime("%Y-%m-%d"),
                            "eps_estimate":  eps_est,
                            "eps_actual":    eps_act,
                            "surprise_pct":  None,
                        })
                        continue
            except Exception:
                pass

            # Fallback: calendar dict
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
            pass

    results.sort(key=lambda x: x.get("earnings_date") or "9999-99-99")
    return deep_clean({"earnings": results})


SCREENER_UNIVERSE = {
    "Technology":             ["AAPL","MSFT","NVDA","GOOGL","META","AVGO","ORCL","AMD","QCOM","TXN","NOW","CRM","ADBE","SNOW","PLTR","NET","CRWD","ZS","DDOG","INTU","AMAT","MU","MRVL","FTNT","PANW","SHOP","UBER","ARM","SMCI","ASML"],
    "Finance":                ["JPM","BAC","WFC","GS","MS","BLK","V","MA","AXP","C","SCHW","USB","PNC","TFC","COF","MCO","SPGI","CME","ICE","PYPL","KKR","APO","BX","CG"],
    "Healthcare":             ["UNH","JNJ","LLY","ABBV","MRK","TMO","ABT","DHR","AMGN","GILD","ISRG","CVS","MDT","BMY","REGN","VRTX","PFE","BIIB","MRNA","HCA","ELV","CI","HUM","DGX"],
    "Energy":                 ["XOM","CVX","COP","SLB","EOG","MPC","PSX","VLO","OXY","HAL","BKR","DVN","FANG","MRO","HES","LNG","WMB","KMI","OKE","ET"],
    "Consumer Discretionary": ["AMZN","TSLA","HD","NKE","SBUX","MCD","TGT","CMG","LULU","TJX","YUM","BKNG","MAR","HLT","GM","F","ROST","ORLY","AZO","RIVN"],
    "Consumer Staples":       ["WMT","COST","PG","KO","PEP","PM","MO","MDLZ","CL","CHD","GIS","K","SYY","ADM","STZ","MNST","KHC"],
    "Industrials":            ["CAT","DE","BA","HON","RTX","LMT","GE","UPS","FDX","MMM","EMR","ETN","CSX","UNP","NSC","CARR","OTIS","ROK","PWR","CTAS"],
    "Communication":          ["META","GOOGL","NFLX","DIS","CMCSA","T","VZ","SNAP","PINS","SPOT","WBD","FOXA","PARA","TTD","ROKU"],
    "Materials":              ["LIN","APD","ECL","SHW","NEM","FCX","ALB","CF","MOS","DOW","DD","PPG","NUE","STLD","VMC"],
    "Real Estate":            ["AMT","PLD","CCI","EQIX","SPG","O","PSA","WELL","VTR","DLR","EQR","AVB","INVH","SBA","AMH"],
    "Utilities":              ["NEE","DUK","SO","D","AEP","EXC","XEL","AWK","PCG","ES","ED","ETR","FE","AES"],
}

_screener_cache: dict = {}
SCREENER_CACHE_TTL = 25 * 60  # 25 minutes

def _fetch_screener_stock(sym: str) -> Optional[dict]:
    try:
        info = yf.Ticker(sym).info
        price = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if not price:
            return None
        return {
            "ticker":       sym,
            "company":      info.get("longName") or info.get("shortName") or sym,
            "sector":       info.get("sector") or "Unknown",
            "price":        price,
            "change_pct":   clean_float(info.get("regularMarketChangePercent")),
            "market_cap":   clean_float(info.get("marketCap")),
            "pe":           clean_float(info.get("trailingPE")),
            "forward_pe":   clean_float(info.get("forwardPE")),
            "volume":       clean_float(info.get("volume") or info.get("regularMarketVolume")),
            "week52_high":  clean_float(info.get("fiftyTwoWeekHigh")),
            "week52_low":   clean_float(info.get("fiftyTwoWeekLow")),
            "beta":         clean_float(info.get("beta")),
            "div_yield":    clean_float(info.get("dividendYield")),
        }
    except Exception:
        return None

@app.get("/api/screener")
def get_screener(
    sector: str = "Technology",
    min_pe: Optional[float] = None,
    max_pe: Optional[float] = None,
    min_change: Optional[float] = None,
    max_change: Optional[float] = None,
    min_cap: Optional[float] = None,
):
    sector = sector.strip()
    tickers = SCREENER_UNIVERSE.get(sector, SCREENER_UNIVERSE["Technology"])

    now = time.time()
    cached = _screener_cache.get(sector)
    if cached and (now - cached["ts"]) < SCREENER_CACHE_TTL:
        results = cached["data"]
    else:
        with ThreadPoolExecutor(max_workers=15) as pool:
            futures = {pool.submit(_fetch_screener_stock, sym): sym for sym in tickers}
            results = [f.result() for f in as_completed(futures) if f.result()]
        results.sort(key=lambda x: x.get("market_cap") or 0, reverse=True)
        _screener_cache[sector] = {"ts": now, "data": results}

    filtered = results
    if min_pe   is not None: filtered = [r for r in filtered if r["pe"] is not None and r["pe"] >= min_pe]
    if max_pe   is not None: filtered = [r for r in filtered if r["pe"] is not None and r["pe"] <= max_pe]
    if min_change is not None: filtered = [r for r in filtered if r["change_pct"] is not None and r["change_pct"] >= min_change]
    if max_change is not None: filtered = [r for r in filtered if r["change_pct"] is not None and r["change_pct"] <= max_change]
    if min_cap  is not None: filtered = [r for r in filtered if r["market_cap"] is not None and r["market_cap"] >= min_cap]

    return deep_clean({"results": filtered, "sector": sector, "total": len(filtered), "sectors": list(SCREENER_UNIVERSE.keys())})

_EARNINGS_WATCH = [
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AVGO","JPM","V",
    "UNH","JNJ","XOM","WMT","MA","PG","HD","CVX","BAC","ABBV","LLY","MRK",
    "COST","KO","PEP","MCD","TMO","CRM","ACN","AMD","TXN","ORCL","CSCO",
    "QCOM","INTC","IBM","NOW","ADBE","INTU","GS","MS","BLK","RTX","CAT",
    "DE","HON","UPS","BA","GE","LMT","AMGN","GILD","REGN","VRTX","BMY",
    "PFE","MRNA","ISRG","MDT","ABT","NFLX","DIS","CMCSA","T","VZ","NEE",
    "NEM","FCX","LIN","APD","SHW","F","GM","RIVN","PLTR","SNOW","COIN",
]

_upcoming_earnings_cache: dict = {"ts": 0.0, "data": None}
UPCOMING_EARNINGS_TTL = 4 * 3600  # 4 hours

def _fetch_one_earnings(sym: str) -> Optional[dict]:
    try:
        today = datetime.date.today()
        cutoff = today + datetime.timedelta(days=60)
        tk = yf.Ticker(sym)
        info = tk.info
        company = info.get("longName") or info.get("shortName") or sym
        try:
            ed = tk.earnings_dates
            if ed is not None and not ed.empty:
                future = ed[ed.index >= pd.Timestamp(today, tz="America/New_York")]
                if not future.empty:
                    row = future.iloc[-1]
                    edate = future.index[-1].date()
                    if edate <= cutoff:
                        return {
                            "ticker": sym, "company_name": company,
                            "sector": info.get("sector", ""),
                            "earnings_date": str(edate),
                            "eps_estimate": clean_float(row.get("EPS Estimate")),
                            "market_cap": clean_float(info.get("marketCap")),
                        }
        except Exception:
            pass
        cal = tk.calendar
        if cal and isinstance(cal, dict):
            dates = cal.get("Earnings Date", [])
            edate = dates[0] if isinstance(dates, list) and dates else dates
            if hasattr(edate, "date"):
                edate = edate.date()
            if edate and isinstance(edate, datetime.date) and edate <= cutoff:
                return {
                    "ticker": sym, "company_name": company,
                    "sector": info.get("sector", ""),
                    "earnings_date": str(edate),
                    "eps_estimate": clean_float(cal.get("EPS Estimate")),
                    "market_cap": clean_float(info.get("marketCap")),
                }
    except Exception:
        pass
    return None

@app.get("/api/earnings/upcoming")
def get_upcoming_earnings():
    now = time.time()
    if _upcoming_earnings_cache["data"] and (now - _upcoming_earnings_cache["ts"]) < UPCOMING_EARNINGS_TTL:
        return _upcoming_earnings_cache["data"]
    results = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_fetch_one_earnings, sym): sym for sym in _EARNINGS_WATCH}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)
    results.sort(key=lambda x: x.get("earnings_date") or "9999")
    result = deep_clean({"earnings": results, "fetched_at": datetime.datetime.utcnow().isoformat()})
    _upcoming_earnings_cache["ts"] = now
    _upcoming_earnings_cache["data"] = result
    return result

# ---------------------------------------------------------------------------
# Options Analytics endpoint
# ---------------------------------------------------------------------------

_options_cache: dict = {}
OPTIONS_CACHE_TTL = 120  # 2 minutes


@app.get("/api/options/{symbol}")
def get_options(symbol: str):
    symbol = symbol.upper().strip()

    now = time.time()
    cached = _options_cache.get(symbol)
    if cached and (now - cached["ts"]) < OPTIONS_CACHE_TTL:
        return cached["data"]

    try:
        ticker_obj = yf.Ticker(symbol)
        info = ticker_obj.info
        current_price = clean_float(
            info.get("currentPrice") or info.get("regularMarketPrice")
        )
        if current_price is None:
            raise HTTPException(status_code=404, detail="No price data for this symbol.")

        expirations = ticker_obj.options
        if not expirations:
            result = {"available": False, "symbol": symbol, "current_price": current_price}
            _options_cache[symbol] = {"ts": now, "data": result}
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

        # Fetch up to 8 chains once — reused for all three sections
        chains: dict = {}
        for exp in expirations[:8]:
            try:
                chains[exp] = ticker_obj.option_chain(exp)
            except Exception:
                continue

        # ── Implied Moves ────────────────────────────────────────────────────
        implied_moves = []
        for exp, chain in chains.items():
            try:
                calls = chain.calls
                puts = chain.puts
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
                    r = row.iloc[0]
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
                continue

        implied_moves.sort(key=lambda x: x["days_to_expiry"])

        # ── IV Smiles (all fetched chains) ───────────────────────────────────
        smiles: dict = {}
        default_smile_exp = None

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
                        m[s] = {
                            "iv":     iv_pct,
                            "volume": clean_float(row.get("volume")) or 0,
                            "oi":     clean_float(row.get("openInterest")) or 0,
                        }
                    return m

                call_map = build_map(calls)
                put_map  = build_map(puts)

                all_strikes = sorted(set(call_map) | set(put_map))
                if len(all_strikes) <= 5:
                    continue

                atm = min(all_strikes, key=lambda s: abs(s - current_price))

                strikes_data = []
                for s in all_strikes:
                    cd = call_map.get(s, {})
                    pd = put_map.get(s, {})
                    strikes_data.append({
                        "strike":      s,
                        "moneyness":   clean_float(round(s / current_price * 100, 1)),
                        "call_iv":     cd.get("iv"),
                        "put_iv":      pd.get("iv"),
                        "call_volume": cd.get("volume"),
                        "put_volume":  pd.get("volume"),
                        "call_oi":     cd.get("oi"),
                        "put_oi":      pd.get("oi"),
                        "is_atm":      s == atm,
                    })

                atm_idx   = all_strikes.index(atm)
                below_ivs = [put_map[s]["iv"] for s in all_strikes[max(0, atm_idx-2):atm_idx] if s in put_map]
                above_ivs = [put_map[s]["iv"] for s in all_strikes[atm_idx+1:atm_idx+3]        if s in put_map]

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
                    "expiration":     exp,
                    "exp_label":      exp_label(exp),
                    "days_to_expiry": days_to(exp),
                    "strikes":        strikes_data,
                    "atm_strike":     clean_float(atm),
                    "skew_label":     skew_label,
                }
                if default_smile_exp is None:
                    default_smile_exp = exp
            except Exception:
                continue

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
                    civ = c_map.get(s, {}).get("iv")
                    piv = p_map.get(s, {}).get("iv")
                    avg_iv = (
                        (civ + piv) / 2 if (civ and piv) else (civ or piv)
                    )
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

            surface_rows = []
            for pct in [0.90, 0.95, 1.00, 1.05, 1.10]:
                if not valid_strikes:
                    break
                closest = min(valid_strikes, key=lambda s: abs(s - current_price * pct))
                cells = []
                for exp in surface_exps:
                    cell = strike_data.get(closest, {}).get(exp, {})
                    cells.append({
                        "expiration": exp,
                        "exp_label":  exp_label(exp),
                        "avg_iv":     cell.get("avg_iv"),
                        "call_oi":    cell.get("call_oi"),
                        "put_oi":     cell.get("put_oi"),
                        "is_atm":     abs(pct - 1.0) < 0.001,
                    })
                surface_rows.append({
                    "moneyness_pct":   pct * 100,
                    "moneyness_label": f"{int(pct * 100)}%",
                    "strike":          clean_float(closest),
                    "cells":           cells,
                })

            all_ivs = [c["avg_iv"] for r in surface_rows for c in r["cells"] if c.get("avg_iv")]
            surface_data = {
                "rows": surface_rows,
                "expirations": [{"expiration": e, "exp_label": exp_label(e)} for e in surface_exps],
                "iv_min": clean_float(round(min(all_ivs), 1)) if all_ivs else 0,
                "iv_max": clean_float(round(max(all_ivs), 1)) if all_ivs else 100,
            }
        except Exception:
            pass

        is_sparse = len(implied_moves) < 3 or len(smiles) < 2

        result = deep_clean({
            "available":           True,
            "symbol":              symbol,
            "current_price":       current_price,
            "implied_moves":       implied_moves,
            "smiles":              smiles,
            "default_smile_exp":   default_smile_exp,
            "available_expirations": [
                {"expiration": e, "exp_label": exp_label(e), "days_to_expiry": days_to(e)}
                for e in chains.keys()
            ],
            "surface":    surface_data,
            "is_sparse":  is_sparse,
        })

        _options_cache[symbol] = {"ts": now, "data": result}
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Options fetch failed: {str(e)}")


# ---------------------------------------------------------------------------
# AI Analysis — streaming SSE endpoint
# ---------------------------------------------------------------------------
@app.get("/api/analyze/{symbol}")
async def analyze_ticker(symbol: str, authorization: Optional[str] = Header(None)):
    """Stream a Claude AI analysis of the ticker. Auth required."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to use AI Analysis")
    try:
        decode_token(authorization.split(" ", 1)[1])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    symbol = symbol.upper().strip()

    # ── Gather data ──────────────────────────────────────────────────────────
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

        # 90-day price history for technicals
        hist = tk.history(period="90d", interval="1d")
        rsi_val = None
        sma50   = None
        sma200  = None
        wk52_hi = clean_float(info.get("fiftyTwoWeekHigh"))
        wk52_lo = clean_float(info.get("fiftyTwoWeekLow"))

        if not hist.empty and len(hist) > 14:
            close = hist["Close"]
            rsi_series = calc_rsi(close)
            rsi_val = round(float(rsi_series.iloc[-1]), 1) if not pd.isna(rsi_series.iloc[-1]) else None
            if len(close) >= 50:
                sma50 = round(float(close.rolling(50).mean().iloc[-1]), 2)
            if len(close) >= 200:
                sma200 = round(float(close.rolling(200).mean().iloc[-1]), 2)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {e}")

    # ── Build prompt ─────────────────────────────────────────────────────────
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

    # ── Stream from Claude ───────────────────────────────────────────────────
    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                yield f"data: {json.dumps({'error': 'ANTHROPIC_API_KEY not configured. Add it to your .env file or Railway environment variables.'})}\n\n"
                return
            ai_client = anthropic.Anthropic(api_key=api_key)
            with ai_client.messages.stream(
                model="claude-haiku-4-5",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    chunk = json.dumps({"text": text})
                    yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
