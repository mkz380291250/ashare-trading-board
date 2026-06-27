import pandas as pd
from app.discovery.qlib_provider import score_panel, latest_section


def _panel():
    # 两天 × 三股,两个因子;MultiIndex(datetime, instrument)
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2026-06-24", "2026-06-25"]), ["A", "B", "C"]],
        names=["datetime", "instrument"])
    return pd.DataFrame({"f1": [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
                         "f2": [3.0, 2.0, 1.0, 1.0, 2.0, 3.0]}, index=idx)


def test_score_panel_returns_score_column():
    s = score_panel(_panel(), {"f1": 1.0, "f2": 1.0})
    assert list(s.columns) == ["score"]
    assert len(s) == 6


def test_latest_section_picks_last_day_sorted_desc():
    s = score_panel(_panel(), {"f1": 1.0, "f2": -1.0})  # f1 越大越好,f2 反向
    sec = latest_section(s)
    # 2026-06-25 截面:A f1=3,f2=1 -> 最高;C f1=1,f2=3 -> 最低
    assert sec.index[0] == "A"
    assert sec.index[-1] == "C"
    assert sec.is_monotonic_decreasing
