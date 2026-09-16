import pandas as pd
from app.factors.frozen import select_frozen


def test_select_dedup_and_signs():
    ranked = ["a", "b", "c"]          # 已按 |IR| 降序
    rank_ic = {"a": -0.05, "b": 0.04, "c": -0.03}
    # a 与 c 高度相关(0.9),应丢掉排名靠后的 c;b 独立
    corr = pd.DataFrame(
        [[1.0, 0.1, 0.9], [0.1, 1.0, 0.1], [0.9, 0.1, 1.0]],
        index=ranked, columns=ranked)
    ff = select_frozen(ranked, rank_ic, corr, universe="investable", horizon=5,
                       source_report="factor_mining_2026-06-25", as_of="2026-06-25",
                       metrics={"rank_ic_mean": 0.07}, threshold=0.8)
    assert ff.factors == ["a", "b"]            # c 被相关去重
    assert ff.signs == {"a": -1.0, "b": 1.0}   # a 反向、b 正向
    assert ff.weights == {"a": 0.5, "b": 0.5}  # 等权
    assert ff.horizon == 5
    assert ff.universe == "investable"
    assert ff.source_report == "factor_mining_2026-06-25"
    assert ff.as_of == "2026-06-25"
    assert ff.metrics_at_freeze == {"rank_ic_mean": 0.07}


def test_select_frozen_with_family_and_ir_weights():
    ranked = ["v1", "v2", "v3", "q1"]
    rank_ic = {"v1": -0.05, "v2": -0.04, "v3": -0.03, "q1": 0.02}
    corr = pd.DataFrame([[1, .2, .2, .1], [.2, 1, .2, .1], [.2, .2, 1, .1], [.1, .1, .1, 1]],
                        index=ranked, columns=ranked, dtype=float)
    ff = select_frozen(ranked, rank_ic, corr, universe="cyb", horizon=20,
                       source_report="r", as_of="2026-09-16", metrics={},
                       family={"v1": "波动", "v2": "波动", "v3": "波动", "q1": "质量"},
                       family_cap=2, ir_map={"v1": -1.0, "v2": -0.8, "q1": 0.4})
    assert ff.factors == ["v1", "v2", "q1"]
    assert abs(sum(ff.weights.values()) - 1.0) < 1e-5
    assert ff.weights["v1"] > ff.weights["q1"]
    assert ff.signs == {"v1": -1.0, "v2": -1.0, "q1": 1.0}
