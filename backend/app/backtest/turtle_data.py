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


def index_close(code: str, db_path: str = "data/tushare_extra.db") -> pd.Series:
    """指数收盘序列:tushare_extra.db 的 ts_index_daily(到 2026-09-14),之后用 baostock 续到最新
    (失败则到库内为止)。code 形如 399006.SZ / 000300.SH。"""
    import sqlite3
    con = sqlite3.connect(db_path)
    df = pd.read_sql_query("select trade_date, close from ts_index_daily where ts_code=? order by 1",
                           con, params=(code,))
    con.close()
    s = pd.Series(df["close"].astype(float).values,
                  index=pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d"))
    try:
        from app.data.baostock_source import BaostockSource
        num, ex = code.split(".")
        src = BaostockSource()
        ext = src.index_daily(f"{ex.lower()}.{num}", (s.index[-1] + pd.Timedelta(days=1)).date(),
                              pd.Timestamp.today().date())
        src.close()
        if ext is not None and len(ext):
            e = pd.Series(ext["close"].astype(float).values, index=pd.to_datetime(ext["date"]))
            s = pd.concat([s, e[~e.index.isin(s.index)]]).sort_index()
    except Exception:       # noqa: BLE001 — 续接失败不影响研究
        pass
    return s


def gate_from_index(idx: pd.Series, dates: pd.DatetimeIndex, ma: int) -> np.ndarray:
    """指数收盘 > MA(ma) 为 True;缺日 ffill;ma<=0 → 全 True。"""
    if ma <= 0:
        return np.ones(len(dates), dtype=bool)
    g = (idx > idx.rolling(ma, min_periods=ma).mean())
    return g.reindex(dates).ffill().fillna(False).to_numpy(dtype=bool)


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
    if "hi55_raw" in px.columns:
        adj["hi55"] = px["hi55_raw"] * f
    tr = pd.concat([adj["high"] - adj["low"], (adj["high"] - adj["pre_close"]).abs(),
                    (adj["low"] - adj["pre_close"]).abs()], axis=1).max(axis=1)
    atr = tr.groupby(level="instrument").transform(lambda s: s.rolling(20, min_periods=20).mean())
    wide = lambda s: s.unstack("instrument")               # noqa: E731
    o, h, l, c = wide(adj["open"]), wide(adj["high"]), wide(adj["low"]), wide(adj["close"])
    ro, rpc = wide(px["open"]), wide(px["pre_close"])
    hi20, atr_w = wide(adj["hi20"]), wide(atr)
    hi55 = wide(adj["hi55"]) if "hi55" in adj.columns else None
    sc = wide(score["score"]).reindex(index=c.index, columns=c.columns)
    if start is not None:
        keep = c.index >= pd.Timestamp(start)
        o, h, l, c, ro, rpc, hi20, atr_w, sc = (x[keep] for x in (o, h, l, c, ro, rpc, hi20, atr_w, sc))
        if hi55 is not None:
            hi55 = hi55[keep]
    dates = pd.DatetimeIndex(c.index)
    codes = list(c.columns)
    a = lambda d: d.to_numpy(dtype="float32")              # noqa: E731
    return Panel(dates=dates.values, codes=codes, open=a(o), high=a(h), low=a(l), close=a(c),
                 raw_open=a(ro), raw_pre_close=a(rpc), score=a(sc), atr=a(atr_w), hi20=a(hi20),
                 limit=limit_matrix(dates, codes), hi55=a(hi55) if hi55 is not None else None)


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
                          "Max(Ref($high,1),20)", "Max(Ref($high,1),55)"], start_time=warm, end_time=end)
    px.columns = ["open", "high", "low", "close", "factor", "pre_close", "hi20_raw", "hi55_raw"]
    px = px.reorder_levels(["datetime", "instrument"]).sort_index()
    ff = load_frozen(frozen_path)
    df = D.features(cfg, [FACTOR_LIBRARY[n] for n in ff.factors], start_time=warm, end_time=end)
    df.columns = list(ff.factors)
    score = composite_score(to_datetime_instrument(df), ff.signs, ff.weights)
    return panel_from_frames(px, score, start=s0)
