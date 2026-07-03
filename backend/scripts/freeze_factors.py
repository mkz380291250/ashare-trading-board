"""从最新 factor_mining_*.json 产出冻结复合因子产物 frozen_composite.json。
复用 run_composite_backtest 的选因子逻辑:robust 因子 -> 截面 z-score 相关去重 -> 等权。"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from app.config import get_settings
from app.backtest.qlib_data import init_qlib
from app.quant.ml_pipeline import cs_zscore
from app.quant.factor_mine import FACTOR_LIBRARY, to_datetime_instrument
from app.factors.frozen import select_frozen, save_frozen, FrozenFactors


def frozen_path(settings) -> Path:
    return Path(settings.qlib_data_dir).resolve().parent / "factors" / "frozen_composite.json"


def _latest_mining(reports_dir: Path) -> dict:
    files = [f for f in sorted(glob.glob(str(reports_dir / "factor_mining_*.json")))
             if "smoke" not in f]
    if not files:
        raise FileNotFoundError("找不到 factor_mining_*.json,先跑 run_factor_mining.py")
    return json.loads(Path(files[-1]).read_text())


def freeze(settings, *, universe=None, horizon=5, threshold=0.8,
           report_path=None) -> FrozenFactors:
    universe = universe or settings.discovery_universe
    init_qlib(settings.qlib_data_dir)
    from qlib.data import D
    reports_dir = Path(settings.qlib_data_dir).resolve().parent / "reports"
    if report_path:
        mining = json.loads(Path(report_path).read_text())
    else:
        mining = _latest_mining(reports_dir)
    robust = mining["robust_factors"]                  # 已按 |IR| 降序
    ranked = [r["name"] for r in robust]
    rank_ic = {r["name"]: r["rank_ic_oos"] for r in robust}
    insts = D.list_instruments(D.instruments(universe), as_list=True)
    end = D.calendar()[-1]
    fields = [FACTOR_LIBRARY[n] for n in ranked]
    df = D.features(insts, fields, start_time="2025-01-01", end_time=end)
    df.columns = ranked
    df = to_datetime_instrument(df)
    z = pd.DataFrame({n: cs_zscore(df[n]) for n in ranked})
    corr = z.corr()
    ff = select_frozen(ranked, rank_ic, corr, universe=universe, horizon=horizon,
                       source_report=mining.get("as_of", "unknown"),
                       as_of=str(end.date()),
                       metrics=mining.get("composite_metrics", {}), threshold=threshold)
    save_frozen(ff, frozen_path(settings))
    return ff


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--report", default="",
                   help="显式指定 factor_mining_*.json;缺省取目录最新非 smoke")
    p.add_argument("--universe", default=None,
                   help="缺省用 settings.discovery_universe(生产宇宙)")
    args = p.parse_args()
    s = get_settings()
    ff = freeze(s, universe=args.universe, report_path=args.report or None)
    print(f"冻结 {len(ff.factors)} 个因子(universe={ff.universe}) -> {frozen_path(s)}", flush=True)
    print(f"  {ff.factors}", flush=True)


if __name__ == "__main__":
    main()
