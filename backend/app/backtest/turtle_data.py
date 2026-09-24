"""海龟式回测取数:研究库 → Panel(复权 OHLC、未复权 open/pre_close、因子分、ATR20、20 日新高、涨跌停幅)。"""
import numpy as np
import pandas as pd

from app.backtest.turtle import Panel

CYB_20PCT_FROM = pd.Timestamp("2020-08-24")   # 创业板涨跌幅 10% → 20%
WARMUP_DAYS = 60


def limit_matrix(dates: pd.DatetimeIndex, codes: list) -> np.ndarray:
    """(T,N) 涨跌停幅:创业板(30 开头)2020-08-24 起 0.2,之前 0.1;科创(68)0.2;其余 0.1。"""
    T, N = len(dates), len(codes)
    lim = np.full((T, N), 0.1, dtype="float32")
    after = np.asarray(dates >= CYB_20PCT_FROM)
    for j, c in enumerate(codes):
        num = c[2:] if c[:2] in ("SH", "SZ", "BJ") else c.split(".")[0]
        if num.startswith("30"):
            lim[after, j] = 0.2
        elif num.startswith("68"):
            lim[:, j] = 0.2
    return lim


def panel_from_frames(px: pd.DataFrame, score: pd.DataFrame, start=None) -> Panel:
    """px: MultiIndex(datetime, instrument) 列 open/high/low/close/factor/pre_close/hi20_raw
    (均未复权,hi20_raw = 前 20 日最高 high 未复权);score: 同索引单列 'score'。
    复权 = raw × factor;ATR20 在复权空间;hi20 = hi20_raw × factor(同日因子近似)。
    start 给了则裁掉热身期。"""
    px = px.sort_index()
    f = px["factor"]
    adj = pd.DataFrame({
        "open": px["open"] * f, "high": px["high"] * f, "low": px["low"] * f,
        "close": px["close"] * f, "pre_close": px["pre_close"] * f, "hi20": px["hi20_raw"] * f,
    })
    tr = pd.concat([adj["high"] - adj["low"], (adj["high"] - adj["pre_close"]).abs(),
                    (adj["low"] - adj["pre_close"]).abs()], axis=1).max(axis=1)
    atr = tr.groupby(level="instrument").transform(lambda s: s.rolling(20, min_periods=20).mean())
    wide = lambda s: s.unstack("instrument")               # noqa: E731
    o, h, l, c = wide(adj["open"]), wide(adj["high"]), wide(adj["low"]), wide(adj["close"])
    ro, rpc = wide(px["open"]), wide(px["pre_close"])
    hi20, atr_w = wide(adj["hi20"]), wide(atr)
    sc = wide(score["score"]).reindex(index=c.index, columns=c.columns)
    if start is not None:
        keep = c.index >= pd.Timestamp(start)
        o, h, l, c, ro, rpc, hi20, atr_w, sc = (x[keep] for x in (o, h, l, c, ro, rpc, hi20, atr_w, sc))
    dates = pd.DatetimeIndex(c.index)
    codes = list(c.columns)
    a = lambda d: d.to_numpy(dtype="float32")              # noqa: E731
    return Panel(dates=dates.values, codes=codes, open=a(o), high=a(h), low=a(l), close=a(c),
                 raw_open=a(ro), raw_pre_close=a(rpc), score=a(sc), atr=a(atr_w), hi20=a(hi20),
                 limit=limit_matrix(dates, codes))


def load_panel(qlib_dir: str, universe: str, frozen_path: str, start: str, end=None) -> Panel:
    from app.backtest.qlib_data import init_qlib
    from app.factors.frozen import load_frozen
    from app.quant.factor_mine import FACTOR_LIBRARY, to_datetime_instrument
    from app.quant.factor_compose import composite_score
    init_qlib(qlib_dir)
    from qlib.data import D
    cal = D.calendar()
    end = cal[-1] if end is None else min(cal[-1], pd.Timestamp(end))
    s0 = pd.Timestamp(start)
    pos = int(np.searchsorted(cal, s0))
    warm = cal[max(0, pos - WARMUP_DAYS)]
    cfg = D.instruments(universe)
    px = D.features(cfg, ["$open", "$high", "$low", "$close", "$factor", "Ref($close,1)",
                          "Max(Ref($high,1),20)"], start_time=warm, end_time=end)
    px.columns = ["open", "high", "low", "close", "factor", "pre_close", "hi20_raw"]
    px = px.reorder_levels(["datetime", "instrument"]).sort_index()
    ff = load_frozen(frozen_path)
    df = D.features(cfg, [FACTOR_LIBRARY[n] for n in ff.factors], start_time=warm, end_time=end)
    df.columns = list(ff.factors)
    score = composite_score(to_datetime_instrument(df), ff.signs, ff.weights)
    return panel_from_frames(px, score, start=s0)
