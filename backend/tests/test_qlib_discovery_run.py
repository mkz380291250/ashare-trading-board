# backend/tests/test_qlib_discovery_run.py
import json
from datetime import date
import pandas as pd
from sqlalchemy import select
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import DiscoveryPick
from app.factors.frozen import FrozenFactors
from app.discovery.qlib_provider import run_qlib_discovery


def _session():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    return make_session_factory(eng)()


def _fake_features(insts, factors, as_of, lookback):
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2026-06-24", "2026-06-25"]), insts],
        names=["datetime", "instrument"])
    data = {f: list(range(len(idx))) for f in factors}
    return pd.DataFrame(data, index=idx)


def test_run_qlib_discovery_writes_full_ranking():
    s = _session()
    frozen = FrozenFactors(as_of="2026-06-25", factors=["f1"], signs={"f1": 1.0},
                           weights={"f1": 1.0}, universe="investable", horizon=5,
                           source_report="r", metrics_at_freeze={})
    out = run_qlib_discovery(s, date(2026, 6, 25), frozen, ["A", "B", "C"],
                             load_features_fn=_fake_features)
    rows = s.execute(select(DiscoveryPick).order_by(DiscoveryPick.rank)).scalars().all()
    assert len(rows) == 3                      # 全量落库,不止 TopN
    assert rows[0].rank == 1
    assert [r.code for r in rows] == [c for c, _ in out]   # 落库顺序=返回顺序
    assert json.loads(rows[0].factors)         # factors 是合法 JSON


def test_run_qlib_discovery_overwrites_same_day():
    s = _session()
    frozen = FrozenFactors(as_of="2026-06-25", factors=["f1"], signs={"f1": 1.0},
                           weights={"f1": 1.0}, universe="investable", horizon=5,
                           source_report="r", metrics_at_freeze={})
    for _ in range(2):
        run_qlib_discovery(s, date(2026, 6, 25), frozen, ["A", "B"],
                           load_features_fn=_fake_features)
    rows = s.execute(select(DiscoveryPick)).scalars().all()
    assert len(rows) == 2                       # 重复跑同日不累积
