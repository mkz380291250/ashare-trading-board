import numpy as np
import pandas as pd
from app.quant.factor_regimes import (
    REGIMES, daily_rank_ic, aggregate, robust_all_regimes, render_md)


def _panel(days, n=30, corr_sign=1.0, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.MultiIndex.from_product([days, [f"S{i}" for i in range(n)]],
                                     names=["datetime", "instrument"])
    x = rng.normal(size=len(idx))
    y = corr_sign * x + 0.3 * rng.normal(size=len(idx))
    return pd.Series(x, index=idx), pd.Series(y, index=idx)


def test_regimes_cover_2011_to_now_contiguously():
    assert REGIMES[0][2] == "2011-01-01"
    for (_, _, _, e), (_, _, s, _) in zip(REGIMES, REGIMES[1:]):
        assert pd.Timestamp(e) + pd.Timedelta(days=1) == pd.Timestamp(s)
    assert REGIMES[-1][3] == "2099-12-31"
    assert len(REGIMES) == 7


def test_daily_rank_ic_sign():
    days = pd.bdate_range("2025-01-01", periods=10)
    x, y = _panel(days, corr_sign=-1.0)
    ric = daily_rank_ic(x, y)
    assert len(ric) == 10 and (ric < 0).all()


def test_aggregate_buckets_years_and_regimes():
    days = pd.bdate_range("2014-06-20", "2015-07-10")
    x, y = _panel(days)
    ric = daily_rank_ic(x, y)
    agg = aggregate(ric)
    assert set(agg["years"]) == {"2014", "2015"}
    assert {"R1", "R2", "R3"} <= set(agg["regimes"])
    assert "R4" not in agg["regimes"]
    assert agg["regimes"]["R2"]["days"] > agg["regimes"]["R3"]["days"]
    assert agg["overall"]["ic"] > 0.5 and agg["overall"]["ir"] > 0
    assert agg["recent3y"]["days"] == agg["overall"]["days"]


def test_robust_all_regimes_rule():
    base = {f"R{i}": {"ic": 0.02, "ir": 0.3, "days": 50} for i in range(1, 8)}
    good = {"overall": {"ic": 0.03}, "regimes": base}
    assert robust_all_regimes(good)
    flip = {"overall": {"ic": 0.03},
            "regimes": {**base, "R2": {"ic": -0.05, "days": 50}, "R5": {"ic": -0.01, "days": 50}}}
    assert not robust_all_regimes(flip)          # 只有 5 个同号 < 6
    weak = {"overall": {"ic": 0.03},
            "regimes": {**base, **{f"R{i}": {"ic": 0.005, "days": 50} for i in range(1, 4)}}}
    assert not robust_all_regimes(weak)          # 达 0.015 的只有 4 个 < 5
    neg = {"overall": {"ic": -0.03},
           "regimes": {k: {"ic": -0.02, "days": 50} for k in base}}
    assert robust_all_regimes(neg)               # 反向因子同样算稳健


def test_render_md_marks_directions():
    regs = {k: {"ic": -0.03, "ir": -0.5, "days": 100} for k, *_ in REGIMES}
    rep = {"as_of": "2026-09-16", "universe": "cyb_dyn", "horizon": 20, "start": "2011-01-04",
           "regimes": REGIMES, "skipped": [],
           "factors": [{"name": "vol20", "family": "波动", "expr": "Std(...)", "in_frozen": True,
                        "robust_all": True,
                        "agg": {"overall": {"ic": -0.05, "ir": -0.8, "days": 3000},
                                "recent3y": {"ic": -0.06, "ir": -0.9, "days": 700},
                                "years": {}, "regimes": regs}}]}
    md = render_md(rep)
    assert "vol20" in md and "−" in md and "★" in md and "✓" in md
