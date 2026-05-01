from sqlalchemy import Column, Integer, String, DateTime, Float, func
from database import Base


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
