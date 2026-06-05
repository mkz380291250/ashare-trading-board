from datetime import date
from app.db.models import Position, Account, TrackEntry, Decision, DecisionJob
from app.data.minute_universe import minute_universe


def test_union_dedup(session):
    acc = Account(name="main", cash=0.0)
    session.add(acc)
    session.flush()
    session.add(Position(account_id=acc.id, code="600519.SH", shares=100, cost=1.0))
    session.add(TrackEntry(code="000001.SZ", added_on=date(2026, 6, 1),
                           entry_close=10.0))
    session.add(Decision(code="600519.SH", as_of=date(2026, 6, 1), action="BUY",
                         created_at=date(2026, 6, 1)))  # 与持仓重复 -> 去重
    session.add(DecisionJob(code="300750.SZ", created_at=date(2026, 6, 1)))
    session.commit()

    u = minute_universe(session)
    assert set(u) == {"600519.SH", "000001.SZ", "300750.SZ"}
    assert len(u) == 3  # 去重


def test_empty(session):
    assert minute_universe(session) == []
