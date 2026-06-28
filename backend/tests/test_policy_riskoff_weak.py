# backend/tests/test_policy_riskoff_weak.py
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, EquitySnapshot, DecisionOutcome, DiscoveryPick
from app.policy.rules import is_risk_off, weak_holdings


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=0.0)); s.commit()
    return s


def test_risk_off_on_drawdown():
    s = _sess()
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 1), cash=0, market_value=0, total=100.0))
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 2), cash=0, market_value=0, total=75.0))  # -25%
    s.commit()
    off, reason = is_risk_off(s, date(2026, 6, 2), dd_stop=0.20, hitrate_stop=0.40)
    assert off is True and "回撤" in reason


def test_risk_off_on_low_hitrate():
    s = _sess()
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 2), cash=0, market_value=0, total=100.0))
    for i in range(5):  # 5 条 outcome,全未命中 → 胜率 0
        s.add(DecisionOutcome(decision_id=i + 1, code=f"C{i}.SH", decided_on=date(2026, 6, 1),
                              action="BUY", entry_close=10.0, ret_t5=-0.05, hit=False,
                              last_updated=date(2026, 6, 2)))
    s.commit()
    off, reason = is_risk_off(s, date(2026, 6, 2), dd_stop=0.20, hitrate_stop=0.40)
    assert off is True and "胜率" in reason


def test_not_risk_off_when_healthy():
    s = _sess()
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 2), cash=0, market_value=0, total=110.0))
    off, reason = is_risk_off(s, date(2026, 6, 2))
    assert off is False


def test_risk_off_drawdown_wins_over_hitrate():
    s = _sess()
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 1), cash=0, market_value=0, total=100.0))
    s.add(EquitySnapshot(account_id=1, as_of=date(2026, 6, 2), cash=0, market_value=0, total=75.0))  # -25%
    for i in range(5):  # 胜率0%(也会触发),但回撤理由应优先
        s.add(DecisionOutcome(decision_id=i + 1, code=f"C{i}.SH", decided_on=date(2026, 6, 1),
                              action="BUY", entry_close=10.0, ret_t5=-0.05, hit=False,
                              last_updated=date(2026, 6, 2)))
    s.commit()
    off, reason = is_risk_off(s, date(2026, 6, 2), dd_stop=0.20, hitrate_stop=0.40)
    assert off is True
    assert "回撤" in reason
    assert "胜率" not in reason


def _seed_pick(s, as_of, ranked_codes):
    total = len(ranked_codes)
    for rank, code in enumerate(ranked_codes, 1):
        s.add(DiscoveryPick(as_of=as_of, code=code, rank=rank, score=float(total - rank), factors="{}"))


def test_weak_holdings_persistently_bottom():
    s = _sess()
    d = [date(2026, 6, 1) + timedelta(days=i) for i in range(3)]
    # 4 只票,持仓 LOW.SH 连续3天排第4(rank/4=1.0 > 0.5)→ 弱;TOP.SH 排第1 → 不弱
    for dd in d:
        _seed_pick(s, dd, ["TOP.SH", "A.SH", "B.SH", "LOW.SH"])
    s.commit()
    weak = weak_holdings(s, {"TOP.SH", "LOW.SH"}, d[-1], pctl=0.50, consecutive=3)
    assert weak == ["LOW.SH"]


def test_weak_holdings_insufficient_history():
    s = _sess()
    _seed_pick(s, date(2026, 6, 1), ["TOP.SH", "LOW.SH"])
    s.commit()
    assert weak_holdings(s, {"LOW.SH"}, date(2026, 6, 1), consecutive=3) == []
