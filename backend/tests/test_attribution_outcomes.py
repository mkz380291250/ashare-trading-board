# backend/tests/test_attribution_outcomes.py
from datetime import date, timedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Decision, DecisionOutcome, DailyQuote
from app.data.quote_store import QuoteStore
from app.attribution.outcomes import compute_outcome, backfill_outcomes, hit_rate


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_compute_outcome_buy_hit():
    closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]  # t0..t10
    out = compute_outcome("BUY", closes)
    assert out["entry_close"] == 100
    assert abs(out["ret_t5"] - 0.05) < 1e-9
    assert out["hit"] is True            # BUY 且 ret_t5>0
    assert out["ret_t10"] is not None


def test_compute_outcome_sell_hit_on_decline():
    closes = [100, 99, 98, 97, 96, 95]   # 只到 t5
    out = compute_outcome("SELL", closes)
    assert out["hit"] is True            # SELL 且 ret_t5<0 = 卖在下跌前
    assert out["ret_t10"] is None        # 窗口不足


def test_compute_outcome_short_window_no_hit():
    out = compute_outcome("BUY", [100, 101])   # 不足 t5
    assert out["ret_t5"] is None and out["hit"] is None


def _seed_quotes(s, code, start: date, closes: list[float]):
    for i, c in enumerate(closes):
        s.add(DailyQuote(code=code, trade_date=start + timedelta(days=i),
                         open=c, high=c, low=c, close=c, vol=1.0))
    s.commit()


def test_backfill_and_hit_rate():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_quotes(s, "600519.SH", d0, [100, 101, 102, 103, 104, 105])  # 连续6日
    s.add(Decision(as_of=d0, code="600519.SH", action="BUY", confidence=0.8,
                   shares=100, reasoning="", status="APPROVED", created_at=d0))
    s.add(Decision(as_of=d0, code="000001.SZ", action="HOLD", confidence=0.5,
                   shares=0, reasoning="", status="APPROVED", created_at=d0))  # 不计
    s.commit()
    store = QuoteStore(s)
    n = backfill_outcomes(s, store, date(2026, 6, 6), lookback_days=15)
    assert n == 1                                   # 只回填 BUY
    row = s.scalar(select(DecisionOutcome))
    assert row.code == "600519.SH" and row.hit is True
    assert hit_rate(s, window=30, as_of=date(2026, 6, 6)) == 1.0


def test_backfill_idempotent():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_quotes(s, "600519.SH", d0, [100, 101, 102, 103, 104, 105])
    s.add(Decision(as_of=d0, code="600519.SH", action="BUY", confidence=0.8,
                   shares=100, reasoning="", status="APPROVED", created_at=d0))
    s.commit()
    store = QuoteStore(s)
    backfill_outcomes(s, store, date(2026, 6, 6))
    backfill_outcomes(s, store, date(2026, 6, 6))
    assert s.query(DecisionOutcome).count() == 1    # 不累积


def test_hit_rate_excludes_future_outcomes():
    s = _sess()
    s.add(DecisionOutcome(decision_id=1, code="600519.SH", decided_on=date(2026, 6, 4),
                          action="BUY", entry_close=100.0, ret_t5=0.05, hit=True,
                          last_updated=date(2026, 6, 4)))
    s.add(DecisionOutcome(decision_id=2, code="000001.SZ", decided_on=date(2026, 6, 20),
                          action="BUY", entry_close=50.0, ret_t5=-0.05, hit=False,
                          last_updated=date(2026, 6, 20)))  # 晚于 as_of,应被排除
    s.commit()
    assert hit_rate(s, window=30, as_of=date(2026, 6, 10)) == 1.0   # 只算 6/4 那条(命中)
