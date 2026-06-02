from datetime import date
from app.db.models import Account, Position, Trade, EquitySnapshot


def test_account_relationships(session):
    acc = Account(name="main", cash=1000000.0)
    session.add(acc); session.commit()
    pos = Position(account_id=acc.id, code="600519.SH", shares=100, cost=1500.0)
    tr = Trade(account_id=acc.id, code="600519.SH", side="BUY", price=1500.0,
               shares=100, traded_at=date(2026, 5, 29))
    eq = EquitySnapshot(account_id=acc.id, as_of=date(2026, 5, 29),
                        cash=850000.0, market_value=150000.0, total=1000000.0)
    session.add_all([pos, tr, eq]); session.commit()
    assert acc.id is not None
    assert session.query(Position).filter_by(account_id=acc.id).count() == 1
    assert session.query(Trade).one().side == "BUY"
    assert session.query(EquitySnapshot).one().total == 1000000.0
