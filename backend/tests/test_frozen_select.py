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
