"""从最新 factor_mining_*.json 产出冻结复合因子产物 frozen_composite.json。
robust 因子(可再与 regime 报告的 robust_all 取交集、剔除研究专用因子)
-> 截面 z-score 相关 + 族限量去重 -> IR 加权(或等权)。--out 可写候选产物而不覆盖生产。"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from app.config import get_settings, resolve_horizon
from app.backtest.qlib_data import init_qlib
from app.quant.ml_pipeline import cs_zscore
from app.quant.factor_mine import (FACTOR_LIBRARY, FACTOR_FAMILY, RESEARCH_ONLY,
                                   to_datetime_instrument)
from app.factors.frozen import select_frozen, save_frozen, FrozenFactors


def frozen_path(settings) -> Path:
    return Path(settings.qlib_data_dir).resolve().parent / "factors" / "frozen_composite.json"


def _latest_mining(reports_dir: Path) -> dict:
    files = [f for f in sorted(glob.glob(str(reports_dir / "factor_mining_*.json")))
             if "smoke" not in f]
    if not files:
        raise FileNotFoundError("找不到 factor_mining_*.json,先跑 run_factor_mining.py")
    return json.loads(Path(files[-1]).read_text())


def freeze(settings, *, universe=None, horizon=None, threshold=0.8,
           report_path=None, qlib_dir=None, regimes_path=None, family_cap=0,
           ir_weighted=False, out_path=None, exclude=()) -> FrozenFactors:
    universe = universe or settings.discovery_universe
    horizon = resolve_horizon(horizon, settings)
    init_qlib(qlib_dir or settings.qlib_data_dir)
    from qlib.data import D
    reports_dir = Path(settings.qlib_data_dir).resolve().parent / "reports"
    if report_path:
        mining = json.loads(Path(report_path).read_text())
    else:
        mining = _latest_mining(reports_dir)
    robust = mining["robust_factors"]                  # 已按 |IR| 降序
    if regimes_path:
        reg = json.loads(Path(regimes_path).read_text())
        ok = {f["name"] for f in reg["factors"] if f.get("robust_all")}
        robust = [r for r in robust if r["name"] in ok]
    robust = [r for r in robust if r["name"] not in RESEARCH_ONLY and r["name"] not in exclude]
    ranked = [r["name"] for r in robust]
    rank_ic = {r["name"]: r["rank_ic_oos"] for r in robust}
    ir_map = {r["name"]: r["rank_ic_ir_oos"] for r in robust} if ir_weighted else None
    inst_cfg = D.instruments(universe)               # config:动态池按成员窗口取数
    end = D.calendar()[-1]
    fields = [FACTOR_LIBRARY[n] for n in ranked]
    oos_start = (mining.get("oos_window") or ["2025-01-01"])[0]
    df = D.features(inst_cfg, fields, start_time=oos_start, end_time=end)
    df.columns = ranked
    df = to_datetime_instrument(df)
    z = pd.DataFrame({n: cs_zscore(df[n]) for n in ranked})
    corr = z.corr()
    ff = select_frozen(ranked, rank_ic, corr, universe=universe, horizon=horizon,
                       source_report=mining.get("as_of", "unknown"),
                       as_of=str(end.date()),
                       metrics=mining.get("composite_metrics", {}), threshold=threshold,
                       family=FACTOR_FAMILY if family_cap else None,
                       family_cap=family_cap, ir_map=ir_map)
    save_frozen(ff, Path(out_path) if out_path else frozen_path(settings))
    return ff


def build_parser():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--report", default="",
                   help="显式指定 factor_mining_*.json;缺省取目录最新非 smoke")
    p.add_argument("--universe", default=None,
                   help="缺省用 settings.discovery_universe(生产宇宙)")
    p.add_argument("--horizon", type=int, default=None,
                   help="缺省用 settings.discovery_horizon")
    p.add_argument("--qlib-dir", default="", help="缺省生产库;研究库传 data/qlib_cn_full")
    p.add_argument("--regimes", default="",
                   help="factor_regimes_*.json:候选 = mining robust ∩ regime robust_all")
    p.add_argument("--family-cap", type=int, default=0,
                   help=">0 则同族最多保留 N 个(用 FACTOR_FAMILY);0=只按相关去重(旧行为)")
    p.add_argument("--threshold", type=float, default=0.8, help="相关去重阈值")
    p.add_argument("--ir-weighted", action="store_true", help="按 OOS |IR| 截断加权(否则等权)")
    p.add_argument("--exclude", default="",
                   help="逗号分隔的因子名,从候选里剔除(如夜链库暂无 PIT 字段的财务因子)")
    p.add_argument("--out", default="",
                   help="写到该路径(候选产物,不覆盖生产 frozen_composite.json)")
    return p


def main():
    args = build_parser().parse_args()
    s = get_settings()
    ff = freeze(s, universe=args.universe, horizon=args.horizon,
                report_path=args.report or None, qlib_dir=args.qlib_dir or None,
                regimes_path=args.regimes or None, family_cap=args.family_cap,
                threshold=args.threshold, ir_weighted=args.ir_weighted,
                out_path=args.out or None,
                exclude=tuple(x for x in args.exclude.split(",") if x))
    print(f"冻结 {len(ff.factors)} 个因子(universe={ff.universe} horizon={ff.horizon}) "
          f"-> {args.out or frozen_path(s)}", flush=True)
    for f in ff.factors:
        print(f"  {f:14s} sign={ff.signs[f]:+.0f} w={ff.weights[f]:.3f}", flush=True)


if __name__ == "__main__":
    main()
