from datetime import date
import pandas as pd
from app.backtest.factor import build_forward_returns, factor_report


def test_build_forward_returns_next_day_adj():
    prices = {
        (date(2026, 6, 1), "SH600519"): 100.0, (date(2026, 6, 2), "SH600519"): 110.0,
        (date(2026, 6, 1), "SZ000001"): 50.0,  (date(2026, 6, 2), "SZ000001"): 45.0,
    }
    fr = build_forward_returns([date(2026, 6, 1), date(2026, 6, 2)],
                               ["SH600519", "SZ000001"],
                               lambda d, c: prices.get((d, c)))
    assert abs(fr.loc[(pd.Timestamp(2026, 6, 1), "SH600519")] - 0.10) < 1e-9
    assert abs(fr.loc[(pd.Timestamp(2026, 6, 1), "SZ000001")] + 0.10) < 1e-9
    assert pd.Timestamp(2026, 6, 2) not in fr.index.get_level_values("datetime")


def test_factor_report_ic_perfect_positive():
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp(2026, 6, 1), s) for s in ["A", "B", "C", "D"]],
        names=["datetime", "instrument"])
    score = pd.DataFrame({"score": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    fwd = pd.Series([0.01, 0.02, 0.03, 0.04], index=idx)
    rep = factor_report(score, fwd, layers=2)
    assert abs(rep["ic_mean"] - 1.0) < 1e-9
    assert abs(rep["rank_ic_mean"] - 1.0) < 1e-9
    assert rep["layer_returns"][-1] > rep["layer_returns"][0]


def test_factor_report_handles_single_name_day():
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp(2026, 6, 1), "A")], names=["datetime", "instrument"])
    rep = factor_report(pd.DataFrame({"score": [1.0]}, index=idx),
                        pd.Series([0.01], index=idx), layers=2)
    assert rep["ic_mean"] == 0.0 or rep["days"] == 0
