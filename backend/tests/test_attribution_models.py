from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DecisionOutcome, FactorICDaily


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def test_decision_outcome_roundtrip():
    s = _sess()
    s.add(DecisionOutcome(decision_id=7, code="600519.SH", decided_on=date(2026, 6, 4),
                          action="BUY", entry_close=100.0, ret_t1=0.01, ret_t3=0.02,
                          ret_t5=0.03, ret_t10=None, hit=True, last_updated=date(2026, 6, 12)))
    s.commit()
    row = s.scalar(select(DecisionOutcome))
    assert row.decision_id == 7 and row.hit is True and row.ret_t10 is None


def test_factor_ic_daily_roundtrip():
    s = _sess()
    s.add(FactorICDaily(as_of=date(2026, 6, 4), ic=0.025, rank_ic=0.069, n=4800))
    s.commit()
    row = s.scalar(select(FactorICDaily))
    assert row.as_of == date(2026, 6, 4) and row.rank_ic == 0.069 and row.n == 4800
