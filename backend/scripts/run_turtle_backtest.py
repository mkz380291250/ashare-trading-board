"""海龟式集中持仓策略参数扫描:进场(factor/breakout)× 退出(固定比例/ATR)× 时间止损,
IS(start~split)选参、OOS(split~)验证,并列最优参数邻域,给出"可用/不可用"结论。

用法:
  python scripts/run_turtle_backtest.py --frozen data/factors/frozen_composite.json,data/factors/wf_cyb_dyn_candidate.json
  python scripts/run_turtle_backtest.py --grid small --start 2024-01-01 --split 2025-01-01   # 冒烟
产出:data/reports/turtle_backtest_<tag>.{json,md}
"""
import argparse
import itertools
import json
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.turtle import Params, run_turtle, metrics       # noqa: E402

MIN_TRADES_IS = 30
USABLE = {"calmar": 0.5, "profit_factor": 1.3, "n_trades": 20}
_PANEL = None                       # fork 后子进程共享


def build_grid(kind: str, slots: int) -> list[Params]:
    """full: 进场 factor/breakout20 × 无闸;v2: 进场 (factor×gate none/all)+(breakout 20/55 × gate none/entry/all)。"""
    holds = [20, 40, 0]
    fixed = [(sl, rr) for sl in (0.04, 0.06, 0.08, 0.10) for rr in (1.5, 2.0, 3.0)]
    atr = [(2.0, kt) for kt in (2.0, 3.0)]
    variants = [("factor", 20, "none"), ("breakout", 20, "none")]
    if kind == "v2":
        variants = [("factor", 20, "none"), ("factor", 20, "all")] + \
                   [("breakout", n, g) for n in (20, 55) for g in ("none", "entry", "all")]
    if kind == "small":
        variants, holds, fixed, atr = [("breakout", 55, "all")], [0], [(0.06, 2.0)], [(2.0, 2.0)]
    out = []
    for (e, n, g), h in itertools.product(variants, holds):
        out += [Params(entry=e, breakout_n=n, gate=g, exit="fixed", sl=sl, rr=rr, max_hold=h, slots=slots)
                for sl, rr in fixed]
        out += [Params(entry=e, breakout_n=n, gate=g, exit="atr", k_stop=ks, k_trail=kt, max_hold=h, slots=slots)
                for ks, kt in atr]
    return out


def _eval(args):
    p, split_i, bench = args
    res = run_turtle(_PANEL, p)
    return {"params": p.__dict__, "label": p.label(),
            "is": metrics(res, _PANEL.dates, bench, 0, split_i),
            "oos": metrics(res, _PANEL.dates, bench, split_i, None),
            "all": metrics(res, _PANEL.dates, bench),
            "trades_oos": [(t.code, str(_PANEL.dates[t.entry_i])[:10], round(t.entry_px, 3),
                            str(_PANEL.dates[t.exit_i])[:10], round(t.exit_px, 3), t.reason,
                            round(t.ret, 4)) for t in res.trades if t.entry_i >= split_i][:400]}


def bench_daily(db_path: str, code: str, dates) -> np.ndarray:
    con = sqlite3.connect(db_path)
    df = pd.read_sql_query("select trade_date, close from ts_index_daily where ts_code=? order by 1",
                           con, params=(code,))
    con.close()
    s = pd.Series(df["close"].astype(float).values,
                  index=pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d"))
    return s.reindex(pd.DatetimeIndex(dates)).ffill().pct_change().to_numpy()


def neighbours(best: dict, rows: list[dict]) -> list[dict]:
    """最优参数的邻域:同进场/退出/时间止损下,sl 相邻档、rr 相邻档、k_trail 另一档、以及三档时间止损。"""
    b = best["params"]
    out = []
    for r in rows:
        q = r["params"]
        if q["entry"] != b["entry"] or q["exit"] != b["exit"]:
            continue
        same_exit = (q["sl"], q["rr"], q["k_trail"]) == (b["sl"], b["rr"], b["k_trail"])
        if q["max_hold"] != b["max_hold"] and not same_exit:
            continue
        if b["exit"] == "fixed":
            near = (abs(q["sl"] - b["sl"]) <= 0.021 and q["rr"] == b["rr"]) or \
                   (q["sl"] == b["sl"] and abs(q["rr"] - b["rr"]) <= 1.01)
        else:
            near = q["k_stop"] == b["k_stop"]
        if near or same_exit:
            out.append(r)
    return out


def _fmt(m: dict) -> str:
    if not m or m.get("n_trades", 0) == 0 and "ann" not in m:
        return "无交易"
    return (f"年化 {m['ann']:+.1%} 回撤 {m['mdd']:.1%} Calmar {m['calmar']:.2f} 夏普 {m['sharpe']:.2f} "
            f"胜率 {m['win_rate']:.0%} 盈亏比 {m['avg_win_loss']:.2f} 盈利因子 {m['profit_factor']:.2f} "
            f"交易 {m['n_trades']} 均持 {m['avg_hold']:.0f}天 仓位 {m['exposure']:.0%}"
            + (f" 超额年化 {m['excess_ann']:+.1%}" if "excess_ann" in m else ""))


def usable(m: dict) -> bool:
    return all(m.get(k, 0) >= v for k, v in USABLE.items())


def render_md(rep: dict) -> str:
    L = [f"# 海龟式集中持仓回测 {rep['as_of']}", "",
         f"- 宇宙 {rep['universe']} | {rep['start']}~{rep['end']} | IS < {rep['split']} ≤ OOS | "
         f"槽位 {rep['slots']} | 网格 {rep['n_grid']} 组 | 基准 {rep['bench']}",
         f"- 可用标准(OOS):Calmar ≥ {USABLE['calmar']} 且 盈利因子 ≥ {USABLE['profit_factor']} 且 交易 ≥ {USABLE['n_trades']}", ""]
    for fz, blk in rep["by_frozen"].items():
        L.append(f"## 因子分:{fz}")
        L.append(f"**结论:{blk['verdict']}**  ({blk['verdict_reason']})")
        L.append("")
        L.append("### IS 前 5(按 Calmar,交易 ≥ 30)→ OOS")
        for r in blk["top_is"]:
            L.append(f"- `{r['label']}`")
            L.append(f"  - IS  {_fmt(r['is'])}")
            L.append(f"  - OOS {_fmt(r['oos'])}  {'✅可用' if usable(r['oos']) else '❌'}")
        L.append("")
        L.append("### 最优参数邻域(IS → OOS)")
        for r in blk["neighbours"]:
            L.append(f"- `{r['label']}`: IS Calmar {r['is'].get('calmar', 0):.2f} / OOS Calmar {r['oos'].get('calmar', 0):.2f} "
                     f"OOS 年化 {r['oos'].get('ann', 0):+.1%} 回撤 {r['oos'].get('mdd', 0):.1%}")
        L.append("")
        L.append("### 按 OOS Calmar 前 5(事后最优,仅供参考,不作选参依据)")
        for r in blk["top_oos"]:
            L.append(f"- `{r['label']}`: OOS {_fmt(r['oos'])} | IS Calmar {r['is'].get('calmar', 0):.2f}")
        L.append("")
        L.append("### 全网格 OOS 概览")
        oos = [r["oos"] for r in blk["rows"] if r["oos"].get("n_trades", 0) > 0]
        if oos:
            pos = sum(1 for m in oos if m["ann"] > 0)
            L.append(f"- {len(oos)} 组有交易,OOS 年化为正 {pos} 组,Calmar>0.5 {sum(1 for m in oos if m['calmar'] > 0.5)} 组,"
                     f"盈利因子中位 {np.median([m['profit_factor'] for m in oos]):.2f},胜率中位 {np.median([m['win_rate'] for m in oos]):.0%}")
            keys = sorted({(r["params"]["entry"], r["params"]["breakout_n"], r["params"]["gate"]) for r in blk["rows"]})
            for e, n, g in keys:
                sub = [r["oos"] for r in blk["rows"] if (r["params"]["entry"], r["params"]["breakout_n"], r["params"]["gate"]) == (e, n, g)
                       and r["oos"].get("n_trades", 0) > 0]
                subi = [r["is"] for r in blk["rows"] if (r["params"]["entry"], r["params"]["breakout_n"], r["params"]["gate"]) == (e, n, g)
                        and r["is"].get("n_trades", 0) > 0]
                if sub:
                    name = e if e == "factor" else f"{e}{n}"
                    L.append(f"  - {name} gate={g}:IS 年化中位 {np.median([m['ann'] for m in subi]) if subi else 0:+.1%} | "
                             f"OOS 年化中位 {np.median([m['ann'] for m in sub]):+.1%},回撤中位 {np.median([m['mdd'] for m in sub]):.1%},"
                             f"盈利因子中位 {np.median([m['profit_factor'] for m in sub]):.2f},正收益 {sum(m['ann'] > 0 for m in sub)}/{len(sub)}")
        L.append("")
        L.append("### 最优组 OOS 前 10 笔交易")
        for t in blk["top_is"][0]["trades_oos"][:10] if blk["top_is"] else []:
            L.append(f"- {t[0]} {t[1]} @{t[2]} → {t[3]} @{t[4]} {t[5]} {t[6]:+.1%}")
        L.append("")
    return "\n".join(L) + "\n"


def main():
    global _PANEL
    p = argparse.ArgumentParser()
    p.add_argument("--qlib-dir", default="")
    p.add_argument("--universe", default="cyb_dyn")
    p.add_argument("--frozen", default="data/factors/frozen_composite.json")
    p.add_argument("--start", default="2015-01-05")
    p.add_argument("--split", default="2022-01-01")
    p.add_argument("--end", default="")
    p.add_argument("--slots", type=int, default=3)
    p.add_argument("--grid", choices=["full", "v2", "small"], default="full")
    p.add_argument("--gate-ma", type=int, default=20, help="趋势闸:基准指数收盘 > MA(N)")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--bench", default="399006.SZ")
    p.add_argument("--extra-db", default="data/tushare_extra.db")
    p.add_argument("--tag", default="")
    args = p.parse_args()

    from app.config import get_settings
    from app.backtest.turtle_data import load_panel
    s = get_settings()
    qlib_dir = args.qlib_dir or s.qlib_research_dir
    grid = build_grid(args.grid, args.slots)
    rep = {"as_of": pd.Timestamp.today().strftime("%Y-%m-%d"), "universe": args.universe,
           "start": args.start, "split": args.split, "slots": args.slots, "n_grid": len(grid),
           "bench": args.bench, "by_frozen": {}}
    for fz in args.frozen.split(","):
        t0 = time.time()
        _PANEL = load_panel(qlib_dir, args.universe, fz, args.start, args.end or None)
        dates = pd.DatetimeIndex(_PANEL.dates)
        from app.backtest.turtle_data import index_close, gate_from_index
        idx = index_close(args.bench, args.extra_db)
        _PANEL.gate = gate_from_index(idx, dates, args.gate_ma)
        print(f"  gate MA{args.gate_ma} on {args.bench}: open {_PANEL.gate.mean():.0%} of days, "
              f"index through {idx.index[-1].date()}", flush=True)
        rep["end"] = str(dates[-1].date())
        split_i = int(np.searchsorted(dates, pd.Timestamp(args.split)))
        bench = bench_daily(args.extra_db, args.bench, dates)
        print(f"[{Path(fz).stem}] panel {_PANEL.close.shape} loaded in {time.time() - t0:.0f}s; "
              f"IS {dates[0].date()}..{dates[split_i - 1].date()} OOS {dates[split_i].date()}..{dates[-1].date()}",
              flush=True)
        t0 = time.time()
        jobs = [(q, split_i, bench) for q in grid]
        if args.workers > 1:
            with ProcessPoolExecutor(args.workers) as ex:
                rows = list(ex.map(_eval, jobs, chunksize=4))
        else:
            rows = [_eval(j) for j in jobs]
        print(f"  {len(rows)} runs in {time.time() - t0:.0f}s", flush=True)
        cand = [r for r in rows if r["is"].get("n_trades", 0) >= MIN_TRADES_IS]
        top_is = sorted(cand, key=lambda r: -r["is"]["calmar"])[:5]
        top_oos = sorted([r for r in rows if r["oos"].get("n_trades", 0) > 0],
                         key=lambda r: -r["oos"]["calmar"])[:5]
        nb = neighbours(top_is[0], rows) if top_is else []
        if top_is and usable(top_is[0]["oos"]) and top_is[0]["is"]["calmar"] > 0:
            verdict, why = "可用", "IS 最优参数在 OOS 达标"
        elif top_is and top_is[0]["is"]["calmar"] <= 0:
            verdict, why = "不可用", "IS 内没有任何参数组盈利(Calmar ≤ 0)"
        elif top_is:
            m = top_is[0]["oos"]
            why = ", ".join(f"{k} {m.get(k, 0)} < {v}" for k, v in USABLE.items() if m.get(k, 0) < v)
            verdict = "不可用"
        else:
            verdict, why = "不可用", f"IS 无交易数 ≥ {MIN_TRADES_IS} 的参数组"
        for r in top_is:
            print(f"  IS#  {r['label']:45s} IS {_fmt(r['is'])}\n       {'':45s} OOS {_fmt(r['oos'])}", flush=True)
        print(f"  VERDICT[{Path(fz).stem}] {verdict}: {why}", flush=True)
        rep["by_frozen"][Path(fz).stem] = {
            "verdict": verdict, "verdict_reason": why, "top_is": top_is, "top_oos": top_oos,
            "neighbours": nb,
            "rows": [{k: v for k, v in r.items() if k != "trades_oos"} for r in rows]}
    rep_dir = Path(qlib_dir).resolve().parent / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    tag = args.tag or (rep["as_of"] + ("_smoke" if args.grid == "small" else ""))
    (rep_dir / f"turtle_backtest_{tag}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    (rep_dir / f"turtle_backtest_{tag}.md").write_text(render_md(rep))
    print(f"REPORT -> {rep_dir}/turtle_backtest_{tag}.md\nTURTLE_BACKTEST_DONE", flush=True)


if __name__ == "__main__":
    main()
