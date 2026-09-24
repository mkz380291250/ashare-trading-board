"""组合层策略研究:创业板选股腿 × 指数趋势/相对强弱切换 × 沪深300/现金防守腿。

腿(日收益序列):
  CYB  = 创业板 15 只因子组合(周频 TopkDropout,drop2 buf5,无闸)
  CYBI = 创业板指(纯择时对照,分离选股 alpha)
  HS   = 沪深300 指数(ETF 代理,不含分红,略低估)
  CASH = 0
切换规则(信号用上一交易日数据,全仓切换扣 0.3% 往返成本;部分切换按权重变动比例计):
  R0  CYB 常持(基线)
  R1  CYB 若创业板指>MA20 否则 CASH
  R2  CYB 若创业板指>MA20;否则 HS 若沪深300>MA20;否则 CASH
  R3  相对强弱:每周比较创业板指/沪深300 过去 N 日动量,强者且在其 MA20 上方则持该腿(CYB/HS),否则 CASH
  R4  50/50 CYB+HS 各自独立 MA20 闸(闸关的一半转现金)
  R5  R2 + 波动率目标(创业板腿按 20 日波动率缩放到目标年化 25%,上限 100%)
  R6  R1 但用 MA20 与 MA60 双确认(都在上方才持)
每条规则输出 IS(2015~2021)/OOS(2022+)/全期指标。
用法:python scripts/research_regime_strategy.py --frozen data/factors/wf_cyb_dyn_candidate.json [--json out]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COST_SWITCH = 0.003            # 全仓切换往返成本


def stats(r: pd.Series, bench: pd.Series | None = None) -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {"days": len(r)}
    nav = (1 + r).cumprod()
    yrs = len(r) / 243
    ann = float(nav.iloc[-1] ** (1 / yrs) - 1)
    mdd = float((nav / nav.cummax() - 1).min())
    sharpe = float(r.mean() / r.std() * np.sqrt(243)) if r.std() > 0 else 0.0
    by_year = {int(y): round(float((1 + g).prod() - 1), 3) for y, g in r.groupby(r.index.year)}
    out = {"ann": round(ann, 4), "mdd": round(mdd, 4), "calmar": round(ann / abs(mdd), 3) if mdd else 0.0,
           "sharpe": round(sharpe, 3), "worst_year": min(by_year.values()),
           "pos_years": f"{sum(v > 0 for v in by_year.values())}/{len(by_year)}", "years": by_year,
           "days": len(r)}
    if bench is not None:
        b = bench.reindex(r.index).fillna(0.0)
        ex = r - b
        out["excess_ir"] = round(float(ex.mean() / ex.std() * np.sqrt(243)), 3) if ex.std() else 0.0
        out["bench_ann"] = round(float((1 + b).prod() ** (1 / yrs) - 1), 4)
    return out


def apply_weights(legs: pd.DataFrame, w: pd.DataFrame, cost: float = COST_SWITCH) -> pd.Series:
    """legs: 日收益 (T×legs);w: 目标权重 (T×legs),用前一日权重持有当日;权重变动的一半 × cost。"""
    w = w.reindex(legs.index).ffill().fillna(0.0)
    w_lag = w.shift(1).fillna(0.0)
    turnover = (w_lag - w_lag.shift(1).fillna(0.0)).abs().sum(axis=1) / 2.0
    ret = (legs.fillna(0.0) * w_lag).sum(axis=1) - turnover * cost
    return ret


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--frozen", default="data/factors/wf_cyb_dyn_candidate.json")
    p.add_argument("--start", default="2015-01-01")
    p.add_argument("--split", default="2022-01-01")
    p.add_argument("--extra-db", default="data/tushare_extra.db")
    p.add_argument("--json", default="")
    p.add_argument("--legs-cache", default="data/regime_legs.pkl",
                   help="缓存各腿日收益(按 frozen 名区分)")
    p.add_argument("--scan", action="store_true", help="只扫迟滞闸邻域(MA×带宽×成本)")
    args = p.parse_args()

    from app.backtest.turtle_data import index_close
    import scripts.research_simple_bt as sb
    from app.config import get_settings
    from app.backtest.qlib_data import init_qlib

    cache = Path(args.legs_cache)
    legs_all = pd.read_pickle(cache) if cache.exists() else {}
    key = Path(args.frozen).stem
    if key not in legs_all:
        s = get_settings()
        init_qlib(s.qlib_research_dir)
        from qlib.data import D
        from app.factors.frozen import load_frozen
        from app.quant.factor_mine import FACTOR_LIBRARY, to_datetime_instrument
        from app.quant.factor_compose import composite_score
        cfg = D.instruments("cyb_dyn")
        end = D.calendar()[-1]
        feat_start = (pd.Timestamp(args.start) - pd.DateOffset(months=4)).strftime("%Y-%m-%d")
        px = D.features(cfg, ["$close*$factor"], start_time=feat_start, end_time=end)
        px.columns = ["adj"]
        ret = px["adj"].unstack(0).pct_change(fill_method=None)
        ff = load_frozen(args.frozen)
        df = D.features(cfg, [FACTOR_LIBRARY[n] for n in ff.factors], start_time=feat_start, end_time=end)
        df.columns = list(ff.factors)
        score = composite_score(to_datetime_instrument(df), ff.signs, ff.weights)["score"].unstack(1)
        bench0 = sb.bench_returns(args.extra_db, "399006.SZ")
        m = sb.run(score, ret, bench0, args.start, 15, n_drop=2, buffer=5)
        legs_all[key] = m["_daily"]
        pd.to_pickle(legs_all, cache)
        print(f"CYB sleeve computed: {sb._fmt(m) if hasattr(sb, '_fmt') else m['ann']}", flush=True)
    cyb = legs_all[key]

    cybi_px = index_close("399006.SZ", args.extra_db)
    hs_px = index_close("000300.SH", args.extra_db)
    idx = cyb.index
    legs = pd.DataFrame({"CYB": cyb, "CYBI": cybi_px.reindex(idx).ffill().pct_change(),
                         "HS": hs_px.reindex(idx).ffill().pct_change(), "CASH": 0.0}).fillna(0.0)
    # 信号(用完整指数序列算,再对齐)
    def above(px, n):
        return (px > px.rolling(n, min_periods=n).mean()).reindex(idx).ffill().fillna(False)
    c20, c60 = above(cybi_px, 20), above(cybi_px, 60)
    h20 = above(hs_px, 20)
    T = len(idx)
    Z = pd.DataFrame(0.0, index=idx, columns=legs.columns)

    rules = {}
    w = Z.copy(); w["CYB"] = 1.0; rules["R0 CYB常持"] = w
    w = Z.copy(); w["CYB"] = c20.astype(float); w["CASH"] = 1 - w["CYB"]; rules["R1 CYB|MA20→现金"] = w
    w = Z.copy(); w["CYB"] = c20.astype(float); w["HS"] = ((~c20) & h20).astype(float); w["CASH"] = 1 - w["CYB"] - w["HS"]
    rules["R2 CYB|MA20→HS|MA20→现金"] = w
    for N in (60, 120):
        mom_c = cybi_px.pct_change(N).reindex(idx).ffill()
        mom_h = hs_px.pct_change(N).reindex(idx).ffill()
        weekly = pd.Series(idx.isocalendar().week.values, index=idx)
        sel = pd.Series("CASH", index=idx)
        cur = "CASH"
        for i, d in enumerate(idx):
            if i == 0 or weekly.iloc[i] != weekly.iloc[i - 1]:
                if mom_c.iloc[i] >= mom_h.iloc[i]:
                    cur = "CYB" if c20.iloc[i] else ("HS" if h20.iloc[i] else "CASH")
                else:
                    cur = "HS" if h20.iloc[i] else ("CYB" if c20.iloc[i] else "CASH")
            sel.iloc[i] = cur
        w = Z.copy()
        for leg in ("CYB", "HS", "CASH"):
            w[leg] = (sel == leg).astype(float)
        rules[f"R3 相对强弱{N}日+MA20"] = w
    w = Z.copy(); w["CYB"] = 0.5 * c20; w["HS"] = 0.5 * h20; w["CASH"] = 1 - w["CYB"] - w["HS"]
    rules["R4 50/50 各自MA20闸"] = w
    vol = cyb.rolling(20).std() * np.sqrt(243)
    scale = (0.25 / vol).clip(upper=1.0).fillna(1.0)
    w = rules["R2 CYB|MA20→HS|MA20→现金"].copy()
    w["CYB"] = w["CYB"] * scale; w["CASH"] = 1 - w["CYB"] - w["HS"]
    rules["R5 R2+波动率目标25%"] = w
    w = Z.copy(); w["CYB"] = (c20 & c60).astype(float); w["CASH"] = 1 - w["CYB"]; rules["R6 CYB|MA20&MA60→现金"] = w
    w = Z.copy(); w["CYB"] = c20.astype(float); w["HS"] = (~c20).astype(float); rules["R7 CYB|MA20→HS(不看HS闸)"] = w

    # ---- 降低来回穿越成本的变体 ----
    def weekly_reentry(sig: pd.Series) -> pd.Series:
        """闸关当天即出;闸开后只在每周首个交易日进(与选股层实现一致)。"""
        wk = pd.Series(idx.isocalendar().week.values, index=idx)
        out = np.zeros(T, dtype=bool); on = False
        for i in range(T):
            if not sig.iloc[i]:
                on = False
            elif i == 0 or wk.iloc[i] != wk.iloc[i - 1]:
                on = True
            out[i] = on
        return pd.Series(out, index=idx)

    def hysteresis(px: pd.Series, n: int, band: float) -> pd.Series:
        """跌破 MA×(1−band) 出,升回 MA×(1+band) 进。"""
        ma = px.rolling(n, min_periods=n).mean()
        on, out = False, []
        for v, m in zip(px, ma):
            if np.isnan(m):
                out.append(False); continue
            if on and v < m * (1 - band):
                on = False
            elif not on and v > m * (1 + band):
                on = True
            out.append(on)
        return pd.Series(out, index=px.index).reindex(idx).ffill().fillna(False)

    for lab, sig in (("MA20 周一再进", weekly_reentry(c20)),
                     ("MA20 迟滞1%", hysteresis(cybi_px, 20, 0.01)),
                     ("MA20 迟滞2%", hysteresis(cybi_px, 20, 0.02)),
                     ("MA20迟滞1% 周一再进", weekly_reentry(hysteresis(cybi_px, 20, 0.01))),
                     ("MA60 周一再进", weekly_reentry(c60)),
                     ("MA20&60 周一再进", weekly_reentry(c20 & c60))):
        w = Z.copy(); w["CYB"] = sig.astype(float); w["CASH"] = 1 - w["CYB"]; rules[f"R1v {lab}→现金"] = w
    sig = weekly_reentry(c20)
    for keep in (0.3, 0.5):
        w = Z.copy(); w["CYB"] = np.where(sig, 1.0, keep); w["CASH"] = 1 - w["CYB"]
        rules[f"R8 MA20周一再进 闸关留{keep:.0%}"] = w
    sig = weekly_reentry(c20)
    w = Z.copy(); w["CYB"] = sig.astype(float); w["HS"] = ((~sig) & weekly_reentry(h20)).astype(float); w["CASH"] = 1 - w["CYB"] - w["HS"]
    rules["R2v MA20周一再进→HS|MA20→现金"] = w
    w = Z.copy(); w["CYBI"] = c20.astype(float); w["CASH"] = 1 - w["CYBI"]; rules["X1 创业板指|MA20→现金(纯择时)"] = w
    w = Z.copy(); w["HS"] = 1.0; rules["X2 沪深300常持"] = w

    split = pd.Timestamp(args.split)
    bench = legs["CYBI"]
    report = {}
    if args.scan:
        print(f"迟滞闸邻域 [{key}]  IS 年化/回撤/Calmar | OOS 年化/回撤/Calmar | 全期 Calmar 切换/年")
        for n in (10, 15, 20, 25, 30, 60):
            for band in (0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04):
                sig = hysteresis(cybi_px, n, band)
                w = Z.copy(); w["CYB"] = sig.astype(float); w["CASH"] = 1 - w["CYB"]
                r = apply_weights(legs, w)
                a, b, f = stats(r[r.index < split]), stats(r[r.index >= split]), stats(r)
                ww = w.reindex(idx).ffill().fillna(0.0)
                sw = float(((ww - ww.shift(1)).abs().sum(axis=1) / 2.0 > 0.4).sum() / (T / 243))
                print(f"  MA{n:2d} band{band:.3f}: IS {a['ann']:+6.1%}/{a['mdd']:6.1%}/{a['calmar']:4.2f} | "
                      f"OOS {b['ann']:+6.1%}/{b['mdd']:6.1%}/{b['calmar']:4.2f} | 全期 C {f['calmar']:4.2f} 切换 {sw:4.0f}")
        for cost in (0.003, 0.005, 0.008):
            sig = hysteresis(cybi_px, 20, 0.02)
            w = Z.copy(); w["CYB"] = sig.astype(float); w["CASH"] = 1 - w["CYB"]
            r = apply_weights(legs, w, cost=cost)
            b, f = stats(r[r.index >= split]), stats(r)
            print(f"  成本 {cost:.1%}/切换: OOS {b['ann']:+6.1%}/{b['mdd']:6.1%} | 全期 {f['ann']:+6.1%}/{f['mdd']:6.1%} C {f['calmar']:4.2f}")
        sig = hysteresis(cybi_px, 20, 0.02)
        w = Z.copy(); w["CYB"] = sig.astype(float); w["CASH"] = 1 - w["CYB"]
        r = apply_weights(legs, w)
        print("  逐年(MA20 band2%):", stats(r)["years"])
        print("  逐年(基线常持):   ", stats(legs["CYB"])["years"])
        print("  逐年(创业板指):   ", stats(legs["CYBI"])["years"])
        print("REGIME_DONE", flush=True)
        return
    print(f"频段 IS {idx[0].date()}~{split.date()} / OOS {split.date()}~{idx[-1].date()}  基准=创业板指\n")
    for name, w in rules.items():
        r = apply_weights(legs, w)
        full, is_, oos = stats(r, bench), stats(r[r.index < split], bench), stats(r[r.index >= split], bench)
        expo = float(w.drop(columns=["CASH"]).sum(axis=1).mean())
        ww = w.reindex(idx).ffill().fillna(0.0)
        switches = float(((ww - ww.shift(1)).abs().sum(axis=1) / 2.0 > 0.4).sum() / (T / 243))
        report[name] = {"is": is_, "oos": oos, "full": full, "exposure": round(expo, 3), "switches_per_year": round(switches, 1)}
        print(f"{name:34s} 仓位{expo:4.0%} 切换{switches:4.0f}/年 | IS 年化 {is_['ann']:+6.1%} 回撤 {is_['mdd']:6.1%} C {is_['calmar']:4.2f} "
              f"| OOS 年化 {oos['ann']:+6.1%} 回撤 {oos['mdd']:6.1%} C {oos['calmar']:4.2f} 夏普 {oos['sharpe']:4.2f} "
              f"| 全期 年化 {full['ann']:+6.1%} 回撤 {full['mdd']:6.1%} C {full['calmar']:4.2f} 最差年 {full['worst_year']:+.0%} 正年 {full['pos_years']}")
    if args.json:
        Path(args.json).write_text(json.dumps({"frozen": key, "rules": report}, ensure_ascii=False, indent=1))
    print("REGIME_DONE", flush=True)


if __name__ == "__main__":
    main()
