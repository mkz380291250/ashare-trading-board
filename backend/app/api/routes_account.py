from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.db.models import Account, Position, EquitySnapshot
from app.trading.schemas import AccountOut, PositionOut, EquityPoint

router = APIRouter(prefix="/api", tags=["account"])


@router.get("/account/{account_id}", response_model=AccountOut)
def get_account(account_id: int, s: Session = Depends(get_session)):
    acc = s.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    positions = s.scalars(select(Position).where(Position.account_id == account_id)).all()
    return AccountOut(id=acc.id, name=acc.name, cash=acc.cash,
                      positions=[PositionOut(code=p.code, shares=p.shares, cost=p.cost)
                                 for p in positions])


@router.get("/equity/{account_id}", response_model=list[EquityPoint])
def get_equity(account_id: int, s: Session = Depends(get_session)):
    rows = s.scalars(
        select(EquitySnapshot).where(EquitySnapshot.account_id == account_id)
        .order_by(EquitySnapshot.as_of)
    ).all()
    return [EquityPoint(as_of=r.as_of, cash=r.cash,
                        market_value=r.market_value, total=r.total) for r in rows]
