"""因子挖掘 + 有效性验证(双窗稳健检验)。

用法:
  python scripts/run_factor_mining.py                  # 全量
  python scripts/run_factor_mining.py --smoke          # 冒烟(小池短窗)

产出:data/reports/factor_mining_<asof>.{json,md}
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.backtest.qlib_data import init_qlib
from app.backtest.factor import factor_report
from app.quant.factor_mine import (
    FACTOR_LIBRARY, label_expr, to_datetime_instrument,
    rank_by_abs_ir, is_robust)

NOVEL = {"sharpe20", "sharpe60", "corr_rv10", "intra_ret", "intra_range",
         "intra_pos", "gap", "mean_intra20", "ma_dist20", "ma_dist60",
         "amihud20", "maxret20", "minret20", "wvma20", "up_ratio14"}


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="investable")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--is-start", default="2022-01-01")
    p.add_argument("--split", default="2025-01-01")   # IS < split <= OOS
    p.add_argument("--ic-min", type=float, default=0.02)
    p.add_argument("--ir-min", type=float, default=0.3)
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()

    s = get_settings()
    init_qlib(s.qlib_data_dir)
    from qlib.data import D

    end = D.calendar()[-1]
    insts = D.list_instruments(D.instruments(args.universe),
                               as_list=True)
    if args.smoke:
        insts = insts[:300]
        args.is_start, args.split = "2024-01-01", "2024-10-01"
        print(f"SMOKE: {len(insts)} insts", flush=True)

    label = label_expr(args.horizon)
    names = list(FACTOR_LIBRARY)
    fields = [FACTOR_LIBRARY[n] for n in names] + [label]
    print(f"computing {len(names)} factors over {len(insts)} insts "
          f"{args.is_start}..{end.date()}", flush=True)
    df = D.features(insts, fields, start_time=args.is_start, end_time=end)
    df.columns = names + ["label"]
    df = to_datetime_instrument(df)

    import pandas as pd
    dts = df.index.get_level_values("datetime")
    split = pd.Timestamp(args.split)
    is_mask = dts < split
    oos_mask = dts >= split
    y_is, y_oos = df["label"][is_mask], df["label"][oos_mask]

    results = []
    for n in names:
        col_is = df[n][is_mask].to_frame("score")
        col_oos = df[n][oos_mask].to_frame("score")
        rep_is = factor_report(col_is, y_is)
        rep_oos = factor_report(col_oos, y_oos)
        results.append({
            "name": n, "novel": n in NOVEL,
            "expr": FACTOR_LIBRARY[n],
            "rank_ic_is": rep_is["rank_ic_mean"],
            "rank_ic_oos": rep_oos["rank_ic_mean"],
            "rank_ic_ir_oos": rep_oos["rank_ic_ir"],
            "rank_ic_ir_is": rep_is["rank_ic_ir"],
            "layers_oos": rep_oos["layer_returns"],
            "days_oos": rep_oos["days"],
        })
        print(f"  {n:14s} IS={rep_is['rank_ic_mean']:+.4f} "
              f"OOS={rep_oos['rank_ic_mean']:+.4f} IR_oos={rep_oos['rank_ic_ir']:+.2f}"
              f"{' ★' if n in NOVEL else ''}", flush=True)

    for r in results:
        r["robust"] = is_robust(r, ic_min=args.ic_min, ir_min=args.ir_min)
    ranked = rank_by_abs_ir(results, key="rank_ic_ir_oos")
    robust = [r for r in ranked if r["robust"]]
    print(f"\nROBUST {len(robust)}/{len(results)} factors "
          f"(同号 & |OOS RankIC|>={args.ic_min} & |IR|>={args.ir_min}):", flush=True)
    for r in robust:
        sign = "正" if r["rank_ic_oos"] > 0 else "反"
        print(f"  ★{'' if not r['novel'] else '新'} {r['name']:14s} "
              f"OOS RankIC={r['rank_ic_oos']:+.4f} IR={r['rank_ic_ir_oos']:+.2f} ({sign}向)",
              flush=True)

    report = {
        "as_of": end.date().isoformat(), "universe": args.universe,
        "horizon": args.horizon, "is_window": [args.is_start, args.split],
        "oos_window": [args.split, end.date().isoformat()],
        "thresholds": {"ic_min": args.ic_min, "ir_min": args.ir_min},
        "n_factors": len(results), "n_robust": len(robust),
        "robust_factors": robust, "all_factors": ranked,
    }
    rep_dir = Path(s.qlib_data_dir).resolve().parent / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    tag = "smoke" if args.smoke else end.date().isoformat()
    (rep_dir / f"factor_mining_{tag}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2))
    (rep_dir / f"factor_mining_{tag}.md").write_text(_md(report))
    print(f"REPORT -> {rep_dir}/factor_mining_{tag}.json\nFACTOR_MINING_DONE",
          flush=True)


def _md(r):
    L = [f"# 因子挖掘报告 {r['as_of']}", "",
         f"- 股票池 {r['universe']} | 预测 {r['horizon']}日 | "
         f"IS {r['is_window']} / OOS {r['oos_window']}",
         f"- 阈值 |OOS RankIC|>={r['thresholds']['ic_min']} & "
         f"|IR|>={r['thresholds']['ir_min']} | 稳健 {r['n_robust']}/{r['n_factors']}",
         "", "## 稳健有效因子(双窗同号且达标)"]
    for x in r["robust_factors"]:
        tag = "新" if x["novel"] else "  "
        sign = "正" if x["rank_ic_oos"] > 0 else "反"
        L.append(f"- [{tag}] {x['name']}: OOS RankIC {x['rank_ic_oos']:+.4f} / "
                 f"IR {x['rank_ic_ir_oos']:+.2f} ({sign}向) — `{x['expr']}`")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
