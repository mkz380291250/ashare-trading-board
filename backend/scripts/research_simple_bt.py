"""引擎无关的简单回测:周频(每周首个交易日按上一交易日分数)选 top-K 等权持有一周;
退市股数据截止即视为按最后收盘卖出;成本 0.15%/边。对比 old vs candidate。"""
import sys, numpy as np, pandas as pd
from app.backtest.qlib_data import init_qlib
init_qlib("data/qlib_cn_full")
from qlib.data import D
from app.factors.frozen import load_frozen
from app.quant.factor_mine import FACTOR_LIBRARY, to_datetime_instrument
from app.quant.factor_compose import composite_score
UNIV = sys.argv[1] if len(sys.argv) > 1 else "cyb_dyn"
TOPK = int(sys.argv[2]) if len(sys.argv) > 2 else 15
insts = D.list_instruments(D.instruments(UNIV), as_list=True)
end = D.calendar()[-1]
px = D.features(insts, ["$close*$factor"], start_time="2021-12-01", end_time=end)
px.columns = ["adj"]
px = px["adj"].unstack(0)                      # datetime x instrument
ret = px.pct_change(fill_method=None)
bench = D.features(["SH000300"], ["$close"], start_time="2021-12-01", end_time=end)["$close"].droplevel(0).pct_change()
def run(path):
    ff = load_frozen(path)
    df = D.features(insts, [FACTOR_LIBRARY[n] for n in ff.factors], start_time="2021-12-01", end_time=end)
    df.columns = list(ff.factors)
    score = composite_score(to_datetime_instrument(df), ff.signs, ff.weights)["score"].unstack(1)
    dates = [d for d in ret.index if d >= pd.Timestamp("2022-01-01")]
    hold, nav, prev_hold = [], [], set()
    daily, turn = [], 0.0
    week = None
    for d in dates:
        wk = d.isocalendar()[:2]
        if wk != week:                          # 新一周:按上一交易日分数选股
            week = wk
            prev = score.index[score.index < d]
            if len(prev):
                s = score.loc[prev[-1]].dropna()
                s = s[s.index.isin(ret.columns)]
                new = list(s.sort_values(ascending=False).head(TOPK).index)
                turn = len(set(new) - prev_hold) / max(TOPK, 1)
                prev_hold, hold = set(new), new
            else:
                turn = 0.0
        r = ret.loc[d, hold].dropna() if hold else pd.Series(dtype=float)
        pr = float(r.mean()) if len(r) else 0.0
        if wk == d.isocalendar()[:2] and turn:
            pr -= 2 * 0.0015 * turn; turn = 0.0
        daily.append((d, pr))
    s = pd.Series(dict(daily))
    nav = (1 + s).cumprod()
    dd = (nav / nav.cummax() - 1).min()
    yrs = len(s) / 243
    ann = nav.iloc[-1] ** (1 / yrs) - 1
    b = bench.reindex(s.index).fillna(0)
    ex = s - b
    ir = ex.mean() / ex.std() * np.sqrt(243)
    by_year = {y: round(float((1 + g).prod() - 1), 3) for y, g in s.groupby(s.index.year)}
    return ann, dd, ir, nav.iloc[-1] - 1, by_year
for name, p in [("candB", "data/factors/candidate_b_composite.json")]:
    ann, dd, ir, cum, by = run(p)
    print(f"{name} @{UNIV} top{TOPK}: 年化 {ann:+.1%} 回撤 {dd:.1%} 超额IR {ir:+.2f} 累计 {cum:+.1%} 逐年 {by}")
bcum = (1 + bench[bench.index >= "2022-01-01"]).prod() - 1
print(f"沪深300 同期累计 {bcum:+.1%}")
