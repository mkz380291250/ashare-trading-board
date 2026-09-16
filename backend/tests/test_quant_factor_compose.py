import pandas as pd
from datetime import date
from app.quant.factor_compose import (
    sign_correct, dedup_by_correlation, composite_score)


def test_sign_correct():
    assert sign_correct(-0.05) == -1.0
    assert sign_correct(0.03) == 1.0
    assert sign_correct(0.0) == 1.0


def test_dedup_by_correlation_drops_redundant():
    ranked = ["a", "b", "c"]
    corr = pd.DataFrame(
        [[1.0, 0.9, 0.1], [0.9, 1.0, 0.1], [0.1, 0.1, 1.0]],
        index=ranked, columns=ranked)
    kept = dedup_by_correlation(ranked, corr, threshold=0.8)
    # b 与 a 高相关(0.9>0.8),保留排名更高的 a,丢 b;c 独立保留
    assert kept == ["a", "c"]


def test_dedup_uses_absolute_correlation():
    ranked = ["a", "b"]
    corr = pd.DataFrame([[1.0, -0.95], [-0.95, 1.0]], index=ranked, columns=ranked)
    assert dedup_by_correlation(ranked, corr, threshold=0.8) == ["a"]


def _idx(day, codes):
    return pd.MultiIndex.from_tuples(
        [(pd.Timestamp(day), c) for c in codes], names=["datetime", "instrument"])


def test_composite_score_applies_sign_and_averages():
    idx = _idx(date(2026, 6, 1), ["A", "B"])
    # f1 越大越好(sign +1):A 低 B 高
    # f2 反向(sign -1):A 高 B 低 —— 取负后也变成 A 低 B 高
    panel = pd.DataFrame({"f1": [1.0, 2.0], "f2": [2.0, 1.0]}, index=idx)
    score = composite_score(panel, {"f1": 1.0, "f2": -1.0})
    assert score.loc[(pd.Timestamp(2026, 6, 1), "B"), "score"] > \
        score.loc[(pd.Timestamp(2026, 6, 1), "A"), "score"]


def test_composite_score_returns_score_column():
    idx = _idx(date(2026, 6, 1), ["A", "B", "C"])
    panel = pd.DataFrame({"f1": [1.0, 2.0, 3.0]}, index=idx)
    out = composite_score(panel, {"f1": 1.0})
    assert isinstance(out, pd.DataFrame)
    assert list(out.columns) == ["score"]


def test_composite_score_weighted():
    import pytest
    idx = _idx(date(2026, 6, 1), ["A", "B", "C"])
    panel = pd.DataFrame({"f1": [1.0, 2.0, 3.0], "f2": [3.0, 2.0, 1.0]}, index=idx)
    eq = composite_score(panel, {"f1": 1.0, "f2": 1.0})
    assert abs(eq["score"]).max() < 1e-9                       # 等权互相抵消
    w = composite_score(panel, {"f1": 1.0, "f2": 1.0}, weights={"f1": 0.9, "f2": 0.1})
    assert w.loc[(pd.Timestamp(2026, 6, 1), "C"), "score"] > \
        w.loc[(pd.Timestamp(2026, 6, 1), "A"), "score"]
    # 权重全等 ⇒ 与等权完全一致
    same = composite_score(panel, {"f1": 1.0, "f2": 1.0}, weights={"f1": 0.5, "f2": 0.5})
    assert same["score"].sub(eq["score"]).abs().max() < 1e-12


def test_dedup_by_family_caps_per_family_and_corr():
    import numpy as np
    from app.quant.factor_compose import dedup_by_family
    ranked = ["v1", "v2", "v3", "t1", "q1"]
    fam = {"v1": "波动", "v2": "波动", "v3": "波动", "t1": "换手", "q1": "质量"}
    corr = pd.DataFrame(np.eye(5), index=ranked, columns=ranked)
    corr.loc["t1", "v1"] = corr.loc["v1", "t1"] = 0.75          # t1 与 v1 高相关 → 丢
    kept = dedup_by_family(ranked, corr, fam, threshold=0.7, family_cap=2)
    assert kept == ["v1", "v2", "q1"]                           # v3 超族上限,t1 相关被丢


def test_ir_weights_clipped_and_normalized():
    import pytest
    from app.quant.factor_compose import ir_weights
    w = ir_weights(["a", "b", "c"], {"a": -3.0, "b": 0.5, "c": 0.1})   # 均值 1.2 → 截断 [0.6, 2.4]
    assert abs(sum(w.values()) - 1.0) < 1e-5
    assert w["a"] == pytest.approx(2.4 / (2.4 + 0.6 + 0.6), abs=1e-6)
    assert w["b"] == w["c"]
    assert ir_weights([], {}) == {}
