from datetime import date
from app.data.fundamentals import build_fundamentals
from app.db.models import DailyQuote
from app.screener.earnings import Earnings


class FakeEarnings:
    def __init__(self, e):
        self._e = e

    def latest(self, code):
        return self._e


def _seed(session, code, td, **kw):
    base = dict(open=1, high=1, low=1, close=1, vol=1)
    base.update(kw)
    session.add(DailyQuote(code=code, trade_date=td, **base))
    session.commit()


def test_build_fundamentals_from_quote_and_earnings(session):
    _seed(session, "300566.SZ", date(2026, 6, 5),
          pe=34.7, pb=3.17, total_mv=706634.0, turnover_rate=14.0)
    f = build_fundamentals(session, "300566.SZ", date(2026, 6, 5),
                           earnings=FakeEarnings(Earnings(np_yoy=-3.2, rev_yoy=5.5)))
    assert f["pe"] == 34.7 and f["pb"] == 3.17
    assert f["total_mv_亿"] == 70.7        # 706634 万 -> 70.7 亿
    assert f["turnover"] == 14.0
    assert f["np_yoy"] == -3.2 and f["rev_yoy"] == 5.5


def test_build_fundamentals_uses_latest_on_or_before_asof(session):
    _seed(session, "X", date(2026, 6, 3), pe=10.0)
    _seed(session, "X", date(2026, 6, 5), pe=20.0)
    f = build_fundamentals(session, "X", date(2026, 6, 4), earnings=None)
    assert f["pe"] == 10.0   # 6-04 之前最近一条是 6-03


def test_build_fundamentals_no_quote_returns_empty(session):
    assert build_fundamentals(session, "NONE.SZ", date(2026, 6, 5), earnings=None) == {}


def test_build_fundamentals_earnings_error_is_swallowed(session):
    _seed(session, "X", date(2026, 6, 5), pe=20.0)

    class Boom:
        def latest(self, code):
            raise RuntimeError("tushare down")

    f = build_fundamentals(session, "X", date(2026, 6, 5), earnings=Boom())
    assert f == {"pe": 20.0}   # 基本面增速取不到也不崩,保留行情面
