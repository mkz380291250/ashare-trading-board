import numpy as np
import pandas as pd
from scripts.validate_frozen_alignment import alignment_report


def _panel(sign_of_factor):
    # 造 40 天 × 30 只:未来收益 fwd 已知;因子 = sign_of_factor * fwd(+噪声)
    rng = np.random.RandomState(0)
    rows, fwd = [], {}
    dts = pd.date_range("2025-01-01", periods=40, freq="D")
    for dt in dts:
        for i in range(30):
            r = rng.normal()
            rows.append((dt, f"S{i}", sign_of_factor * r + 0.01 * rng.normal()))
            fwd[(dt, f"S{i}")] = r
    idx = pd.MultiIndex.from_tuples([(d, c) for d, c, _ in rows],
                                    names=["datetime", "instrument"])
    panel = pd.DataFrame({"f1": [v for _, _, v in rows]}, index=idx)
    ret = pd.Series({k: v for k, v in fwd.items()})
    ret.index = ret.index.set_names(["datetime", "instrument"])
    return panel, ret


def test_alignment_passes_when_score_predicts_returns():
    panel, ret = _panel(sign_of_factor=1.0)      # 因子与未来收益正相关
    rep = alignment_report(panel, {"f1": 1.0}, ret)
    assert rep["rank_ic"] > 0.05
    assert rep["layers"][-1] >= rep["layers"][0]
    assert rep["passed"] is True


def test_alignment_fails_when_score_anti_predicts():
    panel, ret = _panel(sign_of_factor=-1.0)     # 符号取+1 但因子实际反向 -> 应失败
    rep = alignment_report(panel, {"f1": 1.0}, ret)
    assert rep["passed"] is False
