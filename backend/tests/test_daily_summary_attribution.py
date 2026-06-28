from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import Account, DecisionOutcome, FactorICDaily
from app.reporting.daily_summary import build_daily_summary


def _sess():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Account(id=1, name="main", cash=500_000.0)); s.commit()
    return s


def test_summary_includes_hitrate_and_ic():
    s = _sess()
    d = date(2026, 6, 12)
    s.add(DecisionOutcome(decision_id=1, code="600519.SH", decided_on=date(2026, 6, 4),
                          action="BUY", entry_close=100.0, ret_t5=0.05, hit=True,
                          last_updated=d))
    s.add(FactorICDaily(as_of=date(2026, 6, 4), ic=0.02, rank_ic=0.07, n=4000))
    s.commit()
    text = build_daily_summary(s, d, account_id=1)
    assert "近30日胜率 100%" in text
    assert "滚动RankIC +0.0700" in text


def test_summary_attribution_na_when_empty():
    s = _sess()
    text = build_daily_summary(s, date(2026, 6, 12), account_id=1)
    assert "胜率 N/A" in text
