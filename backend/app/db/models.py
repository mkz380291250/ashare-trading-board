from datetime import date
from sqlalchemy import String, Float, Integer, Date, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    cash: Mapped[float] = mapped_column(Float, default=0.0)
    positions: Mapped[list["Position"]] = relationship(back_populates="account")


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    code: Mapped[str] = mapped_column(String(16))
    shares: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)  # avg cost price
    account: Mapped["Account"] = relationship(back_populates="positions")


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    code: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))  # BUY / SELL
    price: Mapped[float] = mapped_column(Float)
    shares: Mapped[int] = mapped_column(Integer)
    traded_at: Mapped[date] = mapped_column(Date)


class EquitySnapshot(Base):
    __tablename__ = "equity_curve"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    as_of: Mapped[date] = mapped_column(Date)
    cash: Mapped[float] = mapped_column(Float)
    market_value: Mapped[float] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)


class DailyQuote(Base):
    __tablename__ = "daily_quotes"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    pre_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    vol: Mapped[float] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    adj_factor: Mapped[float] = mapped_column(Float, default=1.0)
    turnover_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    circ_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb: Mapped[float | None] = mapped_column(Float, nullable=True)


Index("ix_daily_quotes_trade_date", DailyQuote.trade_date)


class IngestedDay(Base):
    __tablename__ = "ingested_days"
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)


class DiscoveryPick(Base):
    __tablename__ = "discovery_picks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    code: Mapped[str] = mapped_column(String(16))
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    factors: Mapped[str] = mapped_column(String, default="{}")  # JSON text


Index("ix_discovery_picks_as_of", DiscoveryPick.as_of)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    code: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(8))   # BUY/SELL/HOLD
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    reasoning: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String(10), default="PENDING")
    created_at: Mapped[date] = mapped_column(Date)


Index("ix_decisions_as_of", Decision.as_of)


class WatchPoolEntry(Base):
    __tablename__ = "watch_pool"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    first_selected_on: Mapped[date] = mapped_column(Date, primary_key=True)
    theme: Mapped[str] = mapped_column(String(32))
    entry_close: Mapped[float] = mapped_column(Float)
    trigger: Mapped[str] = mapped_column(String, default="{}")  # JSON text
    ret_t1: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t3: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t5: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_t10: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_updated: Mapped[date | None] = mapped_column(Date, nullable=True)
