import pandas as pd
from app.quant.factor_mine import (
    FACTOR_LIBRARY, to_datetime_instrument, rank_by_abs_ir, is_robust)


def test_library_nonempty_and_has_label_free_exprs():
    assert len(FACTOR_LIBRARY) >= 30
    # 值都是 qlib 表达式字符串,且不含未来函数(负 Ref)
    for name, expr in FACTOR_LIBRARY.items():
        assert isinstance(expr, str) and "$" in expr
        assert "Ref($close,-" not in expr.replace(" ", ""), f"{name} 含未来函数"


def test_to_datetime_instrument_swaps_levels():
    idx = pd.MultiIndex.from_tuples(
        [("SH600519", pd.Timestamp(2025, 1, 2)),
         ("SZ000001", pd.Timestamp(2025, 1, 2))],
        names=["instrument", "datetime"])
    df = pd.DataFrame({"f": [1.0, 2.0]}, index=idx)
    out = to_datetime_instrument(df)
    assert out.index.names == ["datetime", "instrument"]
    assert out.loc[(pd.Timestamp(2025, 1, 2), "SH600519"), "f"] == 1.0


def test_rank_by_abs_ir_orders_by_absolute_ir():
    results = [
        {"name": "a", "rank_ic_ir_oos": 0.2},
        {"name": "b", "rank_ic_ir_oos": -0.9},
        {"name": "c", "rank_ic_ir_oos": 0.5},
    ]
    ranked = rank_by_abs_ir(results, key="rank_ic_ir_oos")
    assert [r["name"] for r in ranked] == ["b", "c", "a"]


def test_is_robust_requires_same_sign_and_thresholds():
    # 两窗同号(都正)且都达标 -> 稳健
    assert is_robust({"rank_ic_is": 0.03, "rank_ic_oos": 0.025,
                      "rank_ic_ir_oos": 0.4}, ic_min=0.02, ir_min=0.3)
    # 符号相反 -> 不稳健(样本内正、样本外负)
    assert not is_robust({"rank_ic_is": 0.03, "rank_ic_oos": -0.025,
                          "rank_ic_ir_oos": -0.4}, ic_min=0.02, ir_min=0.3)
    # 样本外太弱 -> 不稳健
    assert not is_robust({"rank_ic_is": 0.03, "rank_ic_oos": 0.005,
                          "rank_ic_ir_oos": 0.1}, ic_min=0.02, ir_min=0.3)


def test_is_robust_handles_negative_factors():
    # 两窗都负(反向因子,如反转/波动)且绝对值达标 -> 稳健
    assert is_robust({"rank_ic_is": -0.04, "rank_ic_oos": -0.03,
                      "rank_ic_ir_oos": -0.5}, ic_min=0.02, ir_min=0.3)
