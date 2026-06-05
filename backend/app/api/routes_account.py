from datetime import date as date_t
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import Account, Position, EquitySnapshot, Trade
from app.trading.schemas import AccountOut, PositionOut, EquityPoint
from app.data.names import NameLookup
from app.data.prices import latest_close
from app.data.quote_store import QuoteStore

router = APIRouter(prefix="/api", tags=["account"])


@router.get("/account/{account_id}", response_model=AccountOut)
def get_account(account_id: int, s: Session = Depends(get_session)):
    acc = s.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    positions = s.scalars(select(Position).where(Position.account_id == account_id)).all()
    store = QuoteStore(s)
    names = NameLookup(s)
    today = date_t.today()
    out = []
    for p in positions:
        lc = latest_close(store, p.code, today)
        buy = s.scalar(select(func.min(Trade.traded_at)).where(
            Trade.account_id == account_id, Trade.code == p.code, Trade.side == "BUY"))
        mv = lc * p.shares if lc is not None else None
        pnl = (lc - p.cost) * p.shares if lc is not None else None
        pnl_pct = (lc / p.cost - 1) if (lc is not None and p.cost) else None
        out.append(PositionOut(code=p.code, name=names.get(p.code), shares=p.shares,
            cost=p.cost, buy_date=buy, last_close=lc, market_value=mv,
            pnl=pnl, pnl_pct=pnl_pct))
    return AccountOut(id=acc.id, name=acc.name, cash=acc.cash, positions=out)


@router.get("/equity/{account_id}", response_model=list[EquityPoint])
def get_equity(account_id: int, s: Session = Depends(get_session)):
    rows = s.scalars(
        select(EquitySnapshot).where(EquitySnapshot.account_id == account_id)
        .order_by(EquitySnapshot.as_of)
    ).all()
    return [EquityPoint(as_of=r.as_of, cash=r.cash,
                        market_value=r.market_value, total=r.total) for r in rows]
