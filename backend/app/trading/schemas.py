from datetime import date
from pydantic import BaseModel


class TradeRequest(BaseModel):
    account_id: int
    code: str
    side: str  # BUY / SELL
    price: float
    shares: int
    on: date


class PositionOut(BaseModel):
    code: str
    name: str = ""
    shares: int
    cost: float
    buy_date: date | None = None
    last_close: float | None = None
    market_value: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None


class AccountOut(BaseModel):
    id: int
    name: str
    cash: float
    positions: list[PositionOut]


class EquityPoint(BaseModel):
    as_of: date
    cash: float
    market_value: float
    total: float
