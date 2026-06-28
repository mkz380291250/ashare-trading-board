# backend/tests/test_policy_factor_decay.py
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import FactorICDaily
from app.policy.rules import factor_decayed


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def _seed_ic(s, start: date, rank_ics: list[float]):
    for i, r in enumerate(rank_ics):
        s.add(FactorICDaily(as_of=start + timedelta(days=i), ic=r, rank_ic=r, n=100))
    s.commit()


def test_decayed_when_last5_below_threshold():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_ic(s, d0, [0.01] * 8)          # 连续低
    assert factor_decayed(s, d0 + timedelta(days=7), window=3, consecutive=5,
                          threshold=0.02) is True


def test_not_decayed_when_recent_recovers():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_ic(s, d0, [0.01, 0.01, 0.01, 0.01, 0.01, 0.05, 0.06, 0.07])  # 近端回升
    assert factor_decayed(s, d0 + timedelta(days=7), window=3, consecutive=5,
                          threshold=0.02) is False


def test_not_decayed_insufficient_history():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_ic(s, d0, [0.01, 0.01])        # 不足 consecutive
    assert factor_decayed(s, d0 + timedelta(days=1), window=3, consecutive=5,
                          threshold=0.02) is False


def test_not_decayed_when_rolling_ic_none_insufficient_window():
    s = _sess()
    d0 = date(2026, 6, 1)
    # Create rows with rank_ic=None so latest_rolling_rank_ic returns None
    for i in range(5):
        s.add(FactorICDaily(as_of=d0 + timedelta(days=i), ic=None, rank_ic=None, n=0))
    s.commit()
    # latest_rolling_rank_ic returns None → factor_decayed returns False
    assert factor_decayed(s, d0 + timedelta(days=4), window=3, consecutive=5,
                          threshold=0.02) is False


def test_exact_threshold_not_decayed():
    s = _sess()
    d0 = date(2026, 6, 1)
    _seed_ic(s, d0, [0.02] * 8)           # 恰好等于阈值
    # 严格 < threshold:等于阈值不算衰减
    assert factor_decayed(s, d0 + timedelta(days=7), window=3, consecutive=5,
                          threshold=0.02) is False
