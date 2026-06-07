import pytest
import pandas as pd
from datetime import date
from app.quant.ml_pipeline import label_expr, make_segments, cs_zscore


def test_label_expr_5day_horizon():
    exprs, names = label_expr(5)
    # T+1 买入,T+6 卖出 -> Ref(-6)/Ref(-1)-1
    assert exprs == ["Ref($close, -6)/Ref($close, -1) - 1"]
    assert names == ["LABEL0"]


def test_label_expr_1day_horizon():
    exprs, _ = label_expr(1)
    assert exprs == ["Ref($close, -2)/Ref($close, -1) - 1"]


def test_make_segments_ordered():
    segs = make_segments(
        train=(date(2021, 1, 1), date(2024, 6, 30)),
        valid=(date(2024, 7, 1), date(2025, 6, 30)),
        test=(date(2025, 7, 1), date(2026, 6, 5)))
    assert segs["train"] == [date(2021, 1, 1), date(2024, 6, 30)]
    assert segs["test"][1] == date(2026, 6, 5)


def test_make_segments_rejects_overlap():
    with pytest.raises(ValueError):
        make_segments(
            train=(date(2021, 1, 1), date(2024, 7, 15)),
            valid=(date(2024, 7, 1), date(2025, 6, 30)),
            test=(date(2025, 7, 1), date(2026, 6, 5)))


def _idx(day_codes):
    return pd.MultiIndex.from_tuples(
        [(pd.Timestamp(d), c) for d, c in day_codes],
        names=["datetime", "instrument"])


def test_cs_zscore_per_day_series():
    idx = _idx([(date(2026, 6, 1), c) for c in "ABC"])
    s = pd.Series([1.0, 2.0, 3.0], index=idx)
    z = cs_zscore(s)
    # ddof=1: [1,2,3] -> mean2 std1 -> [-1,0,1]
    assert abs(z.iloc[0] + 1.0) < 1e-9
    assert abs(z.iloc[1]) < 1e-9
    assert abs(z.iloc[2] - 1.0) < 1e-9


def test_cs_zscore_normalizes_each_day_independently():
    idx = _idx([(date(2026, 6, 1), "A"), (date(2026, 6, 1), "B"),
                (date(2026, 6, 2), "A"), (date(2026, 6, 2), "B")])
    s = pd.Series([10.0, 20.0, 100.0, 300.0], index=idx)
    z = cs_zscore(s)
    # 每日各自标准化:两天都应得到 [-0.707, 0.707]
    day1 = z.xs(pd.Timestamp(2026, 6, 1), level="datetime")
    day2 = z.xs(pd.Timestamp(2026, 6, 2), level="datetime")
    assert abs(day1.iloc[0] - day2.iloc[0]) < 1e-9
    assert day1.iloc[0] < 0 < day1.iloc[1]


def test_cs_zscore_zero_variance_day_is_zero():
    idx = _idx([(date(2026, 6, 1), "A"), (date(2026, 6, 1), "B")])
    s = pd.Series([5.0, 5.0], index=idx)
    z = cs_zscore(s)
    assert z.iloc[0] == 0.0 and z.iloc[1] == 0.0
