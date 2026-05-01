from typing import List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, delete as sa_delete

from config import logger
from database import get_db
from models import PortfolioPosition, WatchlistItem, PriceAlert, Transaction, User
from routers.auth import get_current_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
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
    ticker:       str
    condition:    str   # 'above' | 'below'
    target_price: float

class TransactionBody(BaseModel):
    ticker:  str
    tx_type: str   # 'buy' | 'sell'
    shares:  float
    price:   float
    date:    str   # YYYY-MM-DD
    notes:   str = ''


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------
@router.get("/user/portfolio")
def get_portfolio(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(PortfolioPosition).where(PortfolioPosition.user_id == current_user.id)
    ).scalars().all()
    return {"positions": [{"ticker": r.ticker, "shares": r.shares, "avg_cost": r.avg_cost} for r in rows]}


@router.put("/user/portfolio")
def put_portfolio(body: PortfolioBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        db.execute(sa_delete(PortfolioPosition).where(PortfolioPosition.user_id == current_user.id))
        for p in body.positions:
            db.add(PortfolioPosition(
                user_id=current_user.id,
                ticker=p.ticker.upper().strip(),
                shares=p.shares,
                avg_cost=p.avg_cost,
            ))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Failed to save portfolio for user %s", current_user.id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save portfolio") from exc
    return {"ok": True, "count": len(body.positions)}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
@router.get("/user/watchlist")
def get_user_watchlist(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == current_user.id)
    ).scalars().all()
    return {"tickers": [r.ticker for r in rows]}


@router.put("/user/watchlist")
def put_watchlist(body: WatchlistBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        db.execute(sa_delete(WatchlistItem).where(WatchlistItem.user_id == current_user.id))
        seen: set = set()
        for t in body.tickers:
            t = t.upper().strip()
            if t and t not in seen:
                db.add(WatchlistItem(user_id=current_user.id, ticker=t))
                seen.add(t)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Failed to save watchlist for user %s", current_user.id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save watchlist") from exc
    return {"ok": True, "count": len(seen)}


# ---------------------------------------------------------------------------
# Price alerts
# ---------------------------------------------------------------------------
@router.get("/user/alerts")
def get_alerts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(PriceAlert).where(PriceAlert.user_id == current_user.id)
    ).scalars().all()
    return {"alerts": [
        {"id": r.id, "ticker": r.ticker, "condition": r.condition,
         "target_price": r.target_price, "triggered": bool(r.triggered),
         "created_at": str(r.created_at)}
        for r in rows
    ]}


@router.post("/user/alerts")
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


@router.delete("/user/alerts/{alert_id}")
def delete_alert(alert_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(sa_delete(PriceAlert).where(
        PriceAlert.id == alert_id,
        PriceAlert.user_id == current_user.id,
    ))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------
@router.get("/user/transactions")
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


@router.post("/user/transactions")
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


@router.delete("/user/transactions/{tx_id}")
def delete_transaction(tx_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(sa_delete(Transaction).where(
        Transaction.id == tx_id,
        Transaction.user_id == current_user.id,
    ))
    db.commit()
    return {"ok": True}
