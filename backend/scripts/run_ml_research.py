"""ML 因子研究编排:Alpha158 -> LightGBM 拟合 -> 评估 -> 回测选最优因子组合。

用法:
  python scripts/run_ml_research.py                # 全量(默认切分)
  python scripts/run_ml_research.py --smoke        # 冒烟(小股票池 + 短窗口)

产出:<qlib_data_dir>/../reports/ml_research_<end>.{json,md},并落库 BacktestStore。
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.backtest.qlib_data import init_qlib
from app.backtest.factor import factor_report
from app.backtest.strategy import run_strategy_backtest
from app.backtest.store import BacktestStore
from app.quant.ml_pipeline import (
    make_segments, make_handler, make_dataset, prepare_xy,
    train_lgb, predict_scores, feature_importance)
from app.quant.factor_select import rank_importance, candidate_subsets, pick_best


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _clamp_bt_end(end: date) -> date:
    """qlib 次日撮合:回测末日须比日历末日早 >=1 个交易日。"""
    from qlib.data import D
    cal = [c.date() for c in D.calendar(end_time=end)]
    return cal[-2] if cal and cal[-1] >= end else end


def _make_smoke_universe(qlib_dir: str, src: str, n: int) -> str:
    """从 src instruments 取前 n 只,写 smoke.txt,返回名字。"""
    inst = Path(qlib_dir) / "instruments"
    lines = (inst / f"{src}.txt").read_text().splitlines()[:n]
    (inst / "smoke.txt").write_text("\n".join(lines) + "\n")
    return "smoke"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="investable")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--topk", type=int, default=20)
    p.add_argument("--n-drop", type=int, default=5)
    p.add_argument("--train", default="2021-01-04:2024-06-30")
    p.add_argument("--valid", default="2024-07-01:2025-06-30")
    p.add_argument("--test", default="2025-07-01:2026-06-05")
    p.add_argument("--subset-sizes", default="20,50,100")
    p.add_argument("--single-scan", action="store_true",
                   help="额外扫描全部单因子 IC(慢)")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--no-save", action="store_true")
    args = p.parse_args()

    s = get_settings()
    qlib_dir = s.qlib_data_dir
    init_qlib(qlib_dir)

    universe = args.universe
    if args.smoke:
        universe = _make_smoke_universe(qlib_dir, args.universe, 300)
        args.train, args.valid, args.test = (
            "2024-01-02:2024-08-31", "2024-09-01:2024-12-31",
            "2025-01-02:2025-06-30")
        args.subset_sizes = "20,50"
        print("SMOKE mode: universe=smoke(300), short windows", flush=True)

    tr = tuple(_d(x) for x in args.train.split(":"))
    va = tuple(_d(x) for x in args.valid.split(":"))
    te = tuple(_d(x) for x in args.test.split(":"))
    segments = make_segments(tr, va, te)

    print(f"building dataset: universe={universe} horizon={args.horizon} "
          f"segments={args.train}|{args.valid}|{args.test}", flush=True)
    handler = make_handler(universe, start=tr[0], end=te[1],
                           fit_start=tr[0], fit_end=tr[1], horizon=args.horizon)
    ds = make_dataset(handler, segments)

    x_tr, y_tr = prepare_xy(ds, "train")
    x_va, y_va = prepare_xy(ds, "valid")
    x_te, y_te = prepare_xy(ds, "test")
    print(f"shapes train={x_tr.shape} valid={x_va.shape} test={x_te.shape}",
          flush=True)

    # 全因子模型
    booster = train_lgb(x_tr, y_tr, x_va, y_va)
    pred = predict_scores(booster, x_te)
    rep = factor_report(pred, y_te)
    imp = feature_importance(booster)
    ranked = rank_importance(imp)
    print(f"FULL model rank_ic={rep['rank_ic_mean']:.4f} "
          f"ir={rep['rank_ic_ir']:.3f} top5_factors={ranked[:5]}", flush=True)

    bt_end = _clamp_bt_end(te[1])

    # 单因子 IC 扫描(可选)
    single = {}
    if args.single_scan:
        for col in x_te.columns:
            r = factor_report(x_te[[col]].rename(columns={col: "score"}), y_te)
            single[col] = r["rank_ic_mean"]
        single = dict(sorted(single.items(), key=lambda kv: -abs(kv[1])))

    # 因子子集对比 -> 选最优组合
    sizes = [int(x) for x in args.subset_sizes.split(",")]
    subsets = candidate_subsets(ranked, sizes)
    combo_results = {}
    for name, feats in subsets.items():
        b = train_lgb(x_tr, y_tr, x_va, y_va, feats=feats)
        sc = predict_scores(b, x_te, feats=feats)
        bt = run_strategy_backtest(sc, start=te[0], end=bt_end,
                                   topk=args.topk, n_drop=args.n_drop)
        r = factor_report(sc, y_te)
        combo_results[name] = {**bt, "rank_ic_mean": r["rank_ic_mean"],
                               "rank_ic_ir": r["rank_ic_ir"], "n_feats": len(feats)}
        print(f"  combo {name}({len(feats)}f): "
              f"ann={bt.get('annualized_return')} ir={bt.get('information_ratio')} "
              f"mdd={bt.get('max_drawdown')} rank_ic={r['rank_ic_mean']:.4f}",
              flush=True)

    best_name, best_metrics = pick_best(combo_results, metric="information_ratio")
    print(f"BEST combo = {best_name}: {best_metrics}", flush=True)

    report = {
        "as_of": te[1].isoformat(),
        "universe": universe,
        "horizon": args.horizon,
        "segments": {k: [d.isoformat() for d in v] for k, v in segments.items()},
        "full_model": {"factor_report": rep, "top_factors": ranked[:30]},
        "combos": combo_results,
        "best_combo": {"name": best_name, **best_metrics,
                       "factors": subsets[best_name]},
        "single_factor_rank_ic": single,
    }

    reports_dir = Path(qlib_dir).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    tag = "smoke" if args.smoke else te[1].isoformat()
    jpath = reports_dir / f"ml_research_{tag}.json"
    jpath.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    mpath = reports_dir / f"ml_research_{tag}.md"
    mpath.write_text(_render_md(report))
    print(f"REPORT -> {jpath}", flush=True)

    if not args.no_save:
        session = make_session_factory(make_engine())()
        Base.metadata.create_all(make_engine())
        BacktestStore(session).save(
            signal=f"ml_alpha158_h{args.horizon}_{best_name}",
            start=te[0], end=bt_end,
            params={"universe": universe, "horizon": args.horizon,
                    "best_combo": best_name, "topk": args.topk},
            strategy_metrics=best_metrics, factor_report=rep,
            created_at=date.today())
        print("SAVED backtest run", flush=True)
    print("ML_RESEARCH_DONE", flush=True)


def _render_md(r: dict) -> str:
    lines = [f"# ML 因子研究报告 {r['as_of']}", "",
             f"- 股票池: {r['universe']}  预测周期: {r['horizon']}日",
             f"- 切分: train {r['segments']['train']} / valid "
             f"{r['segments']['valid']} / test {r['segments']['test']}", "",
             "## 全因子模型",
             f"- RankIC 均值 {r['full_model']['factor_report']['rank_ic_mean']:.4f}"
             f" / IR {r['full_model']['factor_report']['rank_ic_ir']:.3f}",
             f"- Top 因子: {', '.join(r['full_model']['top_factors'][:15])}", "",
             "## 因子子集回测对比"]
    for name, m in r["combos"].items():
        lines.append(f"- {name} ({m['n_feats']}因子): 年化 "
                     f"{m.get('annualized_return')} / IR {m.get('information_ratio')}"
                     f" / 回撤 {m.get('max_drawdown')} / RankIC {m['rank_ic_mean']:.4f}")
    b = r["best_combo"]
    lines += ["", f"## 最优组合: {b['name']}",
              f"- 年化 {b.get('annualized_return')} / IR {b.get('information_ratio')}"
              f" / 回撤 {b.get('max_drawdown')}", ""]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
