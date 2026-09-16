"""引擎无关的简单回测(研究对比用):周频(每周首个交易日按上一交易日分数)选 top-K
等权持有一周;退市股数据截止即视为按最后收盘卖出;成本 0.15%/边。

用法:
  python scripts/research_simple_bt.py --universe cyb_dyn --frozen data/factors/frozen_composite.json \
      --start 2015-01-01 --bench 399006.SZ --topk 15 [--json out.json]
--frozen 可多个(逗号分隔),同池同窗对比;--bench 取 tushare_extra.db 的 ts_index_daily。
输出:年化 / 最大回撤 / 相对基准超额IR / 累计 / Calmar / 逐年 / 最差年 / 正收益年占比 / 月胜率。
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COST = 0.0015


def bench_returns(db_path: str, code: str) -> pd.Series:
    con = sqlite3.connect(db_path)
    df = pd.read_sql_query("select trade_date, close from ts_index_daily where ts_code=? order by 1",
                           con, params=(code,))
    con.close()
    s = pd.Series(df["close"].astype(float).values,
                  index=pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d"))
    return s.pct_change()


def run(score: pd.DataFrame, ret: pd.DataFrame, bench: pd.Series, start: str, topk: int) -> dict:
    """score/ret: datetime x instrument。返回指标 dict。"""
    dates = [d for d in ret.index if d >= pd.Timestamp(start)]
    hold, prev_hold, week, turn = [], set(), None, 0.0
    daily = {}
    for d in dates:
        wk = d.isocalendar()[:2]
        if wk != week:
            week = wk
            prev = score.index[score.index < d]
            if len(prev):
                s = score.loc[prev[-1]].dropna()
                s = s[s.index.isin(ret.columns)]
                new = list(s.sort_values(ascending=False).head(topk).index)
                turn = len(set(new) - prev_hold) / max(topk, 1)
                prev_hold, hold = set(new), new
        r = ret.loc[d, hold].dropna() if hold else pd.Series(dtype=float)
        pr = float(r.mean()) if len(r) else 0.0
        if turn:
            pr -= 2 * COST * turn
            turn = 0.0
        daily[d] = pr
    s = pd.Series(daily)
    nav = (1 + s).cumprod()
    mdd = float((nav / nav.cummax() - 1).min())
    yrs = len(s) / 243
    ann = float(nav.iloc[-1] ** (1 / yrs) - 1)
    b = bench.reindex(s.index).fillna(0.0)
    ex = s - b
    ir = float(ex.mean() / ex.std() * np.sqrt(243)) if ex.std() else 0.0
    by_year = {int(y): round(float((1 + g).prod() - 1), 4) for y, g in s.groupby(s.index.year)}
    bench_year = {int(y): round(float((1 + g).prod() - 1), 4) for y, g in b.groupby(b.index.year)}
    ex_year = {y: round(by_year[y] - bench_year.get(y, 0.0), 4) for y in by_year}
    monthly = (1 + s).groupby([s.index.year, s.index.month]).prod() - 1
    bm = (1 + b).groupby([b.index.year, b.index.month]).prod() - 1
    return {
        "ann": round(ann, 4), "mdd": round(mdd, 4), "excess_ir": round(ir, 3),
        "cum": round(float(nav.iloc[-1] - 1), 4), "calmar": round(ann / abs(mdd), 3) if mdd else 0.0,
        "bench_cum": round(float((1 + b).prod() - 1), 4),
        "years": by_year, "excess_years": ex_year,
        "worst_year": round(min(by_year.values()), 4),
        "pos_year_share": round(sum(v > 0 for v in by_year.values()) / len(by_year), 3),
        "excess_pos_year_share": round(sum(v > 0 for v in ex_year.values()) / len(ex_year), 3),
        "monthly_win_vs_bench": round(float((monthly > bm.reindex(monthly.index).fillna(0)).mean()), 3),
        "days": int(len(s)),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qlib-dir", default="")
    p.add_argument("--universe", default="cyb_dyn")
    p.add_argument("--frozen", default="data/factors/frozen_composite.json", help="逗号分隔多个")
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--bench", default="399006.SZ")
    p.add_argument("--topk", type=int, default=15)
    p.add_argument("--extra-db", default="data/tushare_extra.db")
    p.add_argument("--json", default="")
    args = p.parse_args()

    from app.config import get_settings
    from app.backtest.qlib_data import init_qlib
    from app.factors.frozen import load_frozen
    from app.quant.factor_mine import FACTOR_LIBRARY, to_datetime_instrument
    from app.quant.factor_compose import composite_score
    s = get_settings()
    init_qlib(args.qlib_dir or s.qlib_research_dir)
    from qlib.data import D

    inst_cfg = D.instruments(args.universe)          # config:动态池按成员窗口取数
    end = D.calendar()[-1]
    feat_start = (pd.Timestamp(args.start) - pd.DateOffset(months=4)).strftime("%Y-%m-%d")
    px = D.features(inst_cfg, ["$close*$factor"], start_time=feat_start, end_time=end)
    px.columns = ["adj"]
    ret = px["adj"].unstack(0).pct_change(fill_method=None)
    bench = bench_returns(args.extra_db, args.bench)
    out = {}
    for path in args.frozen.split(","):
        ff = load_frozen(path)
        df = D.features(inst_cfg, [FACTOR_LIBRARY[n] for n in ff.factors],
                        start_time=feat_start, end_time=end)
        df.columns = list(ff.factors)
        score = composite_score(to_datetime_instrument(df), ff.signs, ff.weights)["score"].unstack(1)
        m = run(score, ret, bench, args.start, args.topk)
        name = Path(path).stem
        out[name] = m
        print(f"{name:26s} @{args.universe:14s} {args.start}~ top{args.topk} vs {args.bench}: "
              f"年化 {m['ann']:+.1%} 回撤 {m['mdd']:.1%} 超额IR {m['excess_ir']:+.2f} Calmar {m['calmar']:.2f} "
              f"累计 {m['cum']:+.1%}(基准 {m['bench_cum']:+.1%}) 最差年 {m['worst_year']:+.1%} "
              f"正年 {m['pos_year_share']:.0%} 超额正年 {m['excess_pos_year_share']:.0%} 月胜率 {m['monthly_win_vs_bench']:.0%}",
              flush=True)
        print(f"    逐年 {m['years']}", flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps({"universe": args.universe, "start": args.start,
                                               "bench": args.bench, "topk": args.topk,
                                               "results": out}, ensure_ascii=False, indent=1))
    print("SIMPLE_BT_DONE", flush=True)


if __name__ == "__main__":
    main()
