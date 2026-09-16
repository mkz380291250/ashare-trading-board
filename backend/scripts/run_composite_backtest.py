"""复合因子回测(闭环最后一环):
载入稳健因子 -> 符号校正 + 相关性去重 -> 等权合成 -> 扣成本/不扣成本 TopkDropout 回测。

用法:
  python scripts/run_composite_backtest.py                  # OOS 窗口全量
  python scripts/run_composite_backtest.py --smoke
产出:data/reports/composite_backtest_<asof>.{json,md},并落 BacktestStore。
"""
import argparse
import glob
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.backtest.qlib_data import init_qlib
from app.backtest.factor import factor_report
from app.backtest.strategy import run_strategy_backtest, DEFAULT_COST
from app.backtest.store import BacktestStore
from app.quant.ml_pipeline import cs_zscore
from app.quant.factor_mine import FACTOR_LIBRARY, label_expr, to_datetime_instrument
from app.quant.factor_compose import sign_correct, dedup_by_correlation, composite_score

NO_COST = {"open_cost": 0.0, "close_cost": 0.0, "min_cost": 0.0}


def _latest_mining_report(reports_dir: Path) -> dict:
    files = sorted(glob.glob(str(reports_dir / "factor_mining_*.json")))
    files = [f for f in files if "smoke" not in f]
    if not files:
        raise FileNotFoundError("找不到 factor_mining_*.json,先跑 run_factor_mining.py")
    return json.loads(Path(files[-1]).read_text())


def _clamp_end(end: date):
    from qlib.data import D
    cal = [c.date() for c in D.calendar(end_time=end)]
    return cal[-2] if cal and cal[-1] >= end else end


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="investable")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--bt-start", default="2025-01-01")  # OOS 窗口
    p.add_argument("--corr-threshold", type=float, default=0.8)
    p.add_argument("--topk", type=int, default=15)       # 适中集中:10-20 只
    p.add_argument("--n-drop", type=int, default=1)       # 周频下每周最多换 1 只 ≈ 2 笔/周
    p.add_argument("--rebalance", choices=["day", "week"], default="week")
    p.add_argument("--hold-thresh", type=int, default=1)
    p.add_argument("--report", default="",
                   help="显式指定 factor_mining_*.json 路径;缺省取目录最新")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--no-save", action="store_true")
    p.add_argument("--qlib-dir", default="", help="缺省生产库;研究库传 data/qlib_cn_full")
    p.add_argument("--frozen", default="",
                   help="直接回测某 frozen json(factors/signs/weights),不再从 mining 报告选因子")
    p.add_argument("--bt-end", default="", help="回测截止日(缺省日历最后一天)")
    args = p.parse_args()

    s = get_settings()
    qlib_dir = args.qlib_dir or s.qlib_data_dir
    init_qlib(qlib_dir)
    from qlib.data import D

    reports_dir = Path(qlib_dir).resolve().parent / "reports"
    frozen_ff = None
    if args.frozen:
        from app.factors.frozen import load_frozen
        frozen_ff = load_frozen(args.frozen)
        mining = {"as_of": frozen_ff.source_report}
        ranked_names = list(frozen_ff.factors)
        signs = dict(frozen_ff.signs)
        print(f"载入 frozen {args.frozen}:{len(ranked_names)} 因子", flush=True)
    else:
        if args.report:
            mining = json.loads(Path(args.report).read_text())
        else:
            mining = _latest_mining_report(reports_dir)
        robust = mining["robust_factors"]  # 已按 |IR| 降序
        ranked_names = [r["name"] for r in robust]
        signs = {r["name"]: sign_correct(r["rank_ic_oos"]) for r in robust}
        print(f"载入稳健因子 {len(ranked_names)} 个(来自 {mining['as_of']})", flush=True)

    end = D.calendar()[-1]
    if args.bt_end:
        end = pd.Timestamp(args.bt_end)
    insts = D.list_instruments(D.instruments(args.universe), as_list=True)
    bt_start = args.bt_start
    if args.smoke:
        insts = insts[:300]
        bt_start = "2025-07-01"
        print(f"SMOKE: {len(insts)} insts, bt_start={bt_start}", flush=True)

    fields = [FACTOR_LIBRARY[n] for n in ranked_names] + [label_expr(args.horizon)]
    df = D.features(insts, fields, start_time=bt_start, end_time=end)
    df.columns = ranked_names + ["label"]
    df = to_datetime_instrument(df)
    label = df["label"]
    panel = df[ranked_names]

    weights = None
    if frozen_ff is not None:
        kept = ranked_names
        weights = dict(frozen_ff.weights)
    else:
        # 相关性去重(按日截面 z-score 后求整体相关)
        z = pd.DataFrame({n: cs_zscore(panel[n]) for n in ranked_names})
        corr = z.corr()
        kept = dedup_by_correlation(ranked_names, corr, threshold=args.corr_threshold)
        print(f"相关去重(|r|>={args.corr_threshold}): {len(ranked_names)} -> {len(kept)} 个独立因子",
              flush=True)
        print(f"  保留: {kept}", flush=True)

    # 合成(frozen 带权重则加权) + IC 评估
    score = composite_score(panel[kept], {k: signs[k] for k in kept}, weights=weights)
    rep = factor_report(score, label)
    print(f"复合因子 RankIC={rep['rank_ic_mean']:+.4f} IR={rep['rank_ic_ir']:+.2f} "
          f"分层高-低={rep['layer_returns'][-1] - rep['layer_returns'][0]:+.4f}", flush=True)

    # 回测:扣成本 vs 不扣成本
    bt_start_d = datetime.strptime(bt_start, "%Y-%m-%d").date()
    bt_end = _clamp_end(end.date())
    bt_cost = run_strategy_backtest(score, start=bt_start_d, end=bt_end,
                                    topk=args.topk, n_drop=args.n_drop, cost=DEFAULT_COST,
                                    rebalance=args.rebalance, hold_thresh=args.hold_thresh)
    bt_free = run_strategy_backtest(score, start=bt_start_d, end=bt_end,
                                    topk=args.topk, n_drop=args.n_drop, cost=NO_COST,
                                    rebalance=args.rebalance, hold_thresh=args.hold_thresh)
    print(f"扣成本 : 年化 {bt_cost['annualized_return']} / IR {bt_cost['information_ratio']} "
          f"/ 回撤 {bt_cost['max_drawdown']} / 累计 {bt_cost['cum_return']:.4f}", flush=True)
    print(f"换手   : {bt_cost.get('trades_per_week')} 笔/周 "
          f"(共 {bt_cost.get('trades_total')} 笔 / {bt_cost.get('weeks')} 周, "
          f"周换手率 {bt_cost.get('turnover_weekly_mean')})", flush=True)
    print(f"不扣成本: 年化 {bt_free['annualized_return']} / 累计 {bt_free['cum_return']:.4f}",
          flush=True)
    drag = ((bt_free['cum_return'] - bt_cost['cum_return']))
    print(f"成本拖累(累计): {drag:+.4f}", flush=True)

    report = {
        "as_of": bt_end.isoformat(), "universe": args.universe,
        "horizon": args.horizon, "bt_window": [bt_start, bt_end.isoformat()],
        "n_robust_in": len(ranked_names), "kept_factors": kept,
        "signs": {k: signs[k] for k in kept},
        "corr_threshold": args.corr_threshold, "topk": args.topk, "n_drop": args.n_drop,
        "rebalance": args.rebalance, "hold_thresh": args.hold_thresh,
        "weights": weights, "frozen": args.frozen or None,
        "composite_factor_report": rep,
        "backtest_with_cost": bt_cost, "backtest_no_cost": bt_free,
        "cost_drag_cum": drag,
        "caveat": "回测窗口与稳健性验证的 OOS 窗口重叠,符号/选择含轻度乐观;"
                  "非完全独立第三方持出。",
    }
    tag = "smoke" if args.smoke else bt_end.isoformat()
    if args.frozen:
        tag += "_" + Path(args.frozen).stem
    (reports_dir / f"composite_backtest_{tag}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2))
    (reports_dir / f"composite_backtest_{tag}.md").write_text(_md(report))
    print(f"REPORT -> {reports_dir / ('composite_backtest_' + tag + '.json')}", flush=True)

    if not args.no_save:
        session = make_session_factory(make_engine())()
        Base.metadata.create_all(make_engine())
        BacktestStore(session).save(
            signal=f"composite_robust_{len(kept)}f_h{args.horizon}",
            start=bt_start_d, end=bt_end,
            params={"kept": kept, "topk": args.topk, "corr_threshold": args.corr_threshold},
            strategy_metrics=bt_cost, factor_report=rep, created_at=date.today())
        print("SAVED backtest run", flush=True)
    print("COMPOSITE_BACKTEST_DONE", flush=True)


def _md(r: dict) -> str:
    bc, bf = r["backtest_with_cost"], r["backtest_no_cost"]
    L = [f"# 复合因子回测 {r['as_of']}", "",
         f"- 股票池 {r['universe']} / 预测{r['horizon']}日 / 窗口 {r['bt_window']}",
         f"- 入选稳健因子 {r['n_robust_in']} → 相关去重(|r|>={r['corr_threshold']})后 "
         f"{len(r['kept_factors'])} 个独立因子", "",
         "## 保留因子(符号)",
         "  " + ", ".join(f"{k}({'+' if r['signs'][k] > 0 else '−'})"
                          for k in r["kept_factors"]), "",
         "## 复合因子预测力",
         f"- RankIC {r['composite_factor_report']['rank_ic_mean']:+.4f} / "
         f"IR {r['composite_factor_report']['rank_ic_ir']:+.2f}", "",
         "## 回测(TopkDropout, "
         f"topk={r['topk']} n_drop={r['n_drop']} 调仓={r.get('rebalance', 'day')}频)",
         f"- 扣成本:年化 {bc['annualized_return']} / IR {bc['information_ratio']} / "
         f"回撤 {bc['max_drawdown']} / 累计 {bc['cum_return']:+.4f}",
         f"- 换手:{bc.get('trades_per_week')} 笔/周(共 {bc.get('trades_total')} 笔 / "
         f"{bc.get('weeks')} 周,周换手率 {bc.get('turnover_weekly_mean')})",
         f"- 不扣成本:年化 {bf['annualized_return']} / 累计 {bf['cum_return']:+.4f}",
         f"- 成本拖累(累计):{r['cost_drag_cum']:+.4f}", "",
         f"> {r['caveat']}"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
