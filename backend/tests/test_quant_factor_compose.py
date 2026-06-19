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
