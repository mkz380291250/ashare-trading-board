from datetime import date
import pandas as pd
from app.discovery.scorer import DiscoveryScorer
from app.backtest.scores import build_score_frame


def test_build_score_frame_shape_and_symbols():
    data = {
        date(2026, 6, 1): {"mom": {"600519.SH": 0.3, "000001.SZ": 0.1}},
        date(2026, 6, 2): {"mom": {"600519.SH": 0.2, "000001.SZ": 0.4}},
    }
    df = build_score_frame(list(data), lambda d: data[d], DiscoveryScorer(top_n=8))
    assert list(df.index.names) == ["datetime", "instrument"]
    assert df.shape == (4, 1) and "score" in df.columns
    insts = set(df.index.get_level_values("instrument"))
    assert insts == {"SH600519", "SZ000001"}
    s = df.xs(pd.Timestamp(2026, 6, 1), level="datetime")["score"]
    assert s["SH600519"] > s["SZ000001"]


def test_build_score_frame_skips_empty_days():
    data = {date(2026, 6, 1): {}, date(2026, 6, 2): {"mom": {"600519.SH": 0.1}}}
    df = build_score_frame(list(data), lambda d: data[d], DiscoveryScorer(top_n=8))
    assert len(df) == 1
    assert df.index.get_level_values("datetime")[0] == pd.Timestamp(2026, 6, 2)


def test_build_score_frame_empty_when_no_data():
    df = build_score_frame([date(2026, 6, 1)], lambda d: {}, DiscoveryScorer())
    assert df.empty
    assert list(df.index.names) == ["datetime", "instrument"]
