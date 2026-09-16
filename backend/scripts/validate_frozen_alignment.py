"""换代把关:加载 frozen_composite.json,用生产打分函数 composite_score 重算
复合分数,验证它【正向】预测 horizon 日远期收益(OOS RankIC>=+0.05 且分层单调
方向正确)。不通过则退出码 1。防再次上线一个分数与收益反向的组合。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.quant.factor_compose import composite_score
from app.backtest.factor import factor_report

RANK_IC_MIN = 0.05


def alignment_report(panel, signs, fwd_returns, layers: int = 5, weights=None) -> dict:
    score = composite_score(panel, signs, weights=weights)   # 生产同一函数
    rep = factor_report(score, fwd_returns, layers=layers)
    lyr = rep["layer_returns"]
    ric = rep["rank_ic_mean"]
    passed = ric >= RANK_IC_MIN and (len(lyr) >= 2 and lyr[-1] >= lyr[0])
    return {"rank_ic": ric, "layers": lyr, "passed": passed}


def main():
    import argparse
    from app.config import get_settings
    from app.backtest.qlib_data import init_qlib
    from app.factors.frozen import load_frozen
    from app.quant.factor_mine import FACTOR_LIBRARY, label_expr, to_datetime_instrument
    from scripts.freeze_factors import frozen_path

    p = argparse.ArgumentParser()
    p.add_argument("--frozen", default="", help="缺省生产 frozen_composite.json")
    p.add_argument("--qlib-dir", default="", help="缺省生产库")
    p.add_argument("--universe", default="", help="覆盖 frozen 里的宇宙(研究库用 cyb_dyn)")
    p.add_argument("--start", default="2025-01-01", help="验证窗起点")
    args = p.parse_args()

    s = get_settings()
    ff = load_frozen(args.frozen or frozen_path(s))
    init_qlib(args.qlib_dir or s.qlib_data_dir)
    from qlib.data import D
    end = D.calendar()[-1]
    insts = D.list_instruments(D.instruments(args.universe or ff.universe), as_list=True)
    fields = [FACTOR_LIBRARY[n] for n in ff.factors] + [label_expr(ff.horizon)]
    df = D.features(insts, fields, start_time=args.start, end_time=end)
    df.columns = list(ff.factors) + ["label"]
    df = to_datetime_instrument(df)
    panel = df[list(ff.factors)]
    rep = alignment_report(panel, ff.signs, df["label"], weights=ff.weights)
    print(f"universe={ff.universe} horizon={ff.horizon} "
          f"n_factors={len(ff.factors)}", flush=True)
    print(f"OOS RankIC={rep['rank_ic']:+.4f}  分层收益={[round(x,4) for x in rep['layers']]}",
          flush=True)
    print(f"ALIGNMENT {'PASS' if rep['passed'] else 'FAIL'} "
          f"(阈值 RankIC>={RANK_IC_MIN} 且 高分层>=低分层)", flush=True)
    sys.exit(0 if rep["passed"] else 1)


if __name__ == "__main__":
    main()
