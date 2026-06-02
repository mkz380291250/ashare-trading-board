from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Account, Position, Trade, EquitySnapshot
from app.data.prices import PriceProvider


class InsufficientFunds(Exception): ...
class InsufficientShares(Exception): ...


class PaperBroker:
    def __init__(self, session: Session):
        self.s = session

    def get_position(self, account_id: int, code: str) -> Position | None:
        return self.s.scalar(
            select(Position).where(Position.account_id == account_id, Position.code == code)
        )

    def _account(self, account_id: int) -> Account:
        return self.s.get(Account, account_id)

    def buy(self, account_id, code, price, shares, on: date):
        acc = self._account(account_id)
        cost = price * shares
        if cost > acc.cash:
            raise InsufficientFunds(f"need {cost}, have {acc.cash}")
        acc.cash -= cost
        pos = self.get_position(account_id, code)
        if pos is None:
            pos = Position(account_id=account_id, code=code, shares=0, cost=0.0)
            self.s.add(pos)
        new_shares = pos.shares + shares
        pos.cost = (pos.cost * pos.shares + price * shares) / new_shares
        pos.shares = new_shares
        self.s.add(Trade(account_id=account_id, code=code, side="BUY",
                         price=price, shares=shares, traded_at=on))
        self.s.commit()

    def sell(self, account_id, code, price, shares, on: date):
        pos = self.get_position(account_id, code)
        if pos is None or shares > pos.shares:
            raise InsufficientShares(f"sell {shares}, have {pos.shares if pos else 0}")
        acc = self._account(account_id)
        acc.cash += price * shares
        pos.shares -= shares
        if pos.shares == 0:
            self.s.delete(pos)
        self.s.add(Trade(account_id=account_id, code=code, side="SELL",
                         price=price, shares=shares, traded_at=on))
        self.s.commit()

    def mark_to_market(self, account_id, prices: PriceProvider, on: date) -> EquitySnapshot:
        acc = self._account(account_id)
        positions = self.s.scalars(
            select(Position).where(Position.account_id == account_id)
        ).all()
        mv = sum(p.shares * prices.latest_close(p.code) for p in positions)
        snap = EquitySnapshot(account_id=account_id, as_of=on, cash=acc.cash,
                              market_value=mv, total=acc.cash + mv)
        self.s.add(snap); self.s.commit()
        return snap
