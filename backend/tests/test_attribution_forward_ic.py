# backend/tests/test_attribution_forward_ic.py
from datetime import date, timedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DiscoveryPick, FactorICDaily, DailyQuote
from app.data.quote_store import QuoteStore
from app.attribution.forward_ic import daily_ic, backfill_factor_ic, latest_rolling_rank_ic


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_daily_ic_perfect_rank_correlation():
    # score 越高、前向收益越高 → RankIC = 1
    pairs = [(3.0, 0.05), (2.0, 0.03), (1.0, 0.01)]
    ic, ric, n = daily_ic(pairs)
    assert n == 3
    assert abs(ric - 1.0) < 1e-9


def test_daily_ic_no_variance_returns_none():
    ic, ric, n = daily_ic([(1.0, 0.0), (1.0, 0.0)])
    assert ic is None and ric is None


def _seed(s, code, start, closes, score, pick_date):
    for i, c in enumerate(closes):
        s.add(DailyQuote(code=code, trade_date=start + timedelta(days=i),
                         open=c, high=c, low=c, close=c, vol=1.0))
    s.add(DiscoveryPick(as_of=pick_date, code=code, rank=1, score=score, factors="{}"))


def test_backfill_factor_ic_writes_row():
    s = _sess()
    d0 = date(2026, 6, 1)
    # 两只股票,5日后收益与 score 同序 → RankIC 正
    _seed(s, "600519.SH", d0, [100, 100, 100, 100, 100, 110], score=2.0, pick_date=d0)
    _seed(s, "000001.SZ", d0, [50, 50, 50, 50, 50, 51], score=1.0, pick_date=d0)
    s.commit()
    store = QuoteStore(s)
    n = backfill_factor_ic(s, store, date(2026, 6, 7), horizon=5)
    assert n == 1
    row = s.scalar(select(FactorICDaily).where(FactorICDaily.as_of == d0))
    assert row is not None and row.n == 2 and row.rank_ic is not None
    assert latest_rolling_rank_ic(s, as_of=date(2026, 6, 7), window=20) == row.rank_ic
