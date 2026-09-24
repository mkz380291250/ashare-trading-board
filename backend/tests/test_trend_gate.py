import pandas as pd
import pytest
from datetime import date
from app.portfolio.trend_gate import evaluate, load_prev_state, liquidate_all, KIND_ON, KIND_OFF


def _closes(vals, start="2026-08-01"):
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(vals, index=idx)


def test_initial_state_uses_plain_ma():
    s = _closes([100.0] * 19 + [101.0])
    e = evaluate(s, s.index[-1].date(), ma=20, band=0.03, prev_on=None)
    assert e.on is True and e.prev_on is None and not e.changed
    s2 = _closes([100.0] * 19 + [99.0])
    assert evaluate(s2, s2.index[-1].date(), ma=20, band=0.03, prev_on=None).on is False


def test_hysteresis_band_keeps_state_inside_band():
    s = _closes([100.0] * 20 + [98.0])              # −2% 在 3% 带内 → 沿用
    d = s.index[-1].date()
    assert evaluate(s, d, ma=20, band=0.03, prev_on=True).on is True
    assert evaluate(s, d, ma=20, band=0.03, prev_on=False).on is False
    s = _closes([100.0] * 20 + [96.0])              # −4%(MA≈99.8)→ 关
    e = evaluate(s, s.index[-1].date(), ma=20, band=0.03, prev_on=True)
    assert e.on is False and e.changed
    s = _closes([100.0] * 20 + [104.0])             # +4% → 开
    e = evaluate(s, s.index[-1].date(), ma=20, band=0.03, prev_on=False)
    assert e.on is True and e.changed


def test_stale_index_keeps_prev_state():
    s = _closes([100.0] * 20 + [90.0])
    later = date(2026, 12, 31)
    e = evaluate(s, later, ma=20, band=0.03, prev_on=True)
    assert e.stale and e.on is True and "滞后" in e.summary()


def test_insufficient_history_raises():
    s = _closes([100.0] * 5)
    with pytest.raises(ValueError):
        evaluate(s, s.index[-1].date(), ma=20, band=0.03, prev_on=None)


def _db():
    from app.db.database import make_engine, make_session_factory, Base
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    return make_session_factory(eng)()


def test_load_prev_state_reads_latest_record():
    from app.policy.guardrails import record_action
    s = _db()
    assert load_prev_state(s) is None
    record_action(s, KIND_OFF, date(2026, 9, 1), {}, "x")
    record_action(s, KIND_ON, date(2026, 9, 10), {}, "y")
    assert load_prev_state(s) is True
    assert load_prev_state(s, before=date(2026, 9, 10)) is False


def test_liquidate_all_sells_every_position_and_skips_unpriced():
    from app.db.models import Account, Position
    from app.trading.broker import PaperBroker
    s = _db()
    s.add(Account(id=1, name="main", cash=1000.0))
    s.add(Position(account_id=1, code="300001.SZ", shares=100, cost=10.0))
    s.add(Position(account_id=1, code="300002.SZ", shares=200, cost=5.0))
    s.commit()
    pos = s.query(Position).all()
    prices = {"300001.SZ": 12.0, "300002.SZ": None}
    sold = liquidate_all(s, PaperBroker(s), pos, prices.get, date(2026, 9, 24))
    assert sold == ["300001.SZ"]
    acc = s.get(Account, 1)
    assert acc.cash == pytest.approx(1000.0 + 1200.0)
    left = {p.code: p.shares for p in s.query(Position).all() if p.shares > 0}
    assert left == {"300002.SZ": 200}
