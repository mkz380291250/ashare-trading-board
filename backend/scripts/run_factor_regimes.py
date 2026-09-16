"""多 regime 因子重检:在研究库(2010 起)上按年/按 regime 逐因子 RankIC。

用法:
  python scripts/run_factor_regimes.py                       # cyb_dyn, h=settings.discovery_horizon
  python scripts/run_factor_regimes.py --universe cyb_dyn --start 2011-01-04 --qlib-dir data/qlib_cn_full
  python scripts/run_factor_regimes.py --qlib-dir data/qlib_cn --universe cyb --start 2024-01-01 --limit 100  # 冒烟
产出:<qlib_dir>/../reports/factor_regimes_<asof>_h<h>.{json,md}
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, resolve_horizon
from app.backtest.qlib_data import init_qlib, available_fields
from app.quant.factor_mine import FACTOR_LIBRARY, label_expr, to_datetime_instrument
from app.quant.factor_regimes import (REGIMES, daily_rank_ic, aggregate,
                                      robust_all_regimes, render_md, mark)


def _required_fields(name: str) -> set[str]:
    import re
    return set(re.findall(r"\$([a-z_]+)", FACTOR_LIBRARY[name]))


def _family(name: str) -> str:
    try:
        from app.quant.factor_mine import FACTOR_FAMILY
        return FACTOR_FAMILY.get(name, "其他")
    except ImportError:
        return "其他"


def _frozen_names(settings) -> set[str]:
    try:
        from app.factors.frozen import load_frozen
        p = Path(settings.qlib_data_dir).resolve().parent / "factors" / "frozen_composite.json"
        return set(load_frozen(p).factors)
    except Exception:
        return set()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="cyb_dyn")
    p.add_argument("--horizon", type=int, default=None)
    p.add_argument("--start", default="2011-01-04")
    p.add_argument("--qlib-dir", default="", help="缺省 settings.qlib_research_dir")
    p.add_argument("--limit", type=int, default=0, help="冒烟:只取前 N 只")
    p.add_argument("--end", default="", help="截止日(严格样本外检验用)")
    p.add_argument("--chunk-years", type=int, default=0,
                   help=">0 则按 N 年分段取数再拼接(省内存)")
    args = p.parse_args()

    s = get_settings()
    horizon = resolve_horizon(args.horizon, s)
    qlib_dir = args.qlib_dir or s.qlib_research_dir
    init_qlib(qlib_dir)
    from qlib.data import D
    import pandas as pd

    end = D.calendar()[-1]
    if args.end:
        end = min(end, pd.Timestamp(args.end))
    inst_cfg = D.instruments(args.universe)          # 传 config 而非列表:动态池按成员窗口取数
    insts = D.list_instruments(inst_cfg, as_list=True)
    if args.limit:
        from app.backtest.qlib_data import instruments_subset
        insts = insts[: args.limit]
        inst_cfg = D.instruments(instruments_subset(qlib_dir, args.universe, insts,
                                                    f"{args.universe}_lim{args.limit}"))
    avail = set(available_fields(qlib_dir))
    names, skipped = [], []
    for n in FACTOR_LIBRARY:
        (names if _required_fields(n) <= avail else skipped).append(n)
    frozen = _frozen_names(s)
    label = label_expr(horizon)
    print(f"regimes: {len(insts)} insts, {len(names)} factors (skip {skipped}), "
          f"{args.start}..{end.date()} h{horizon} qlib={qlib_dir}", flush=True)

    fields = [FACTOR_LIBRARY[n] for n in names] + [label]
    if args.chunk_years:
        parts = []
        y0, y1 = int(args.start[:4]), end.year
        for y in range(y0, y1 + 1, args.chunk_years):
            a = max(pd.Timestamp(args.start), pd.Timestamp(f"{y}-01-01"))
            b = min(end, pd.Timestamp(f"{y + args.chunk_years - 1}-12-31"))
            d = D.features(inst_cfg, fields, start_time=a, end_time=b)
            d.columns = names + ["label"]
            parts.append(d.astype("float32"))
            print(f"  chunk {a.date()}..{b.date()} rows={len(d)}", flush=True)
        df = pd.concat(parts)
    else:
        df = D.features(inst_cfg, fields, start_time=args.start, end_time=end)
        df.columns = names + ["label"]
        df = df.astype("float32")
    df = to_datetime_instrument(df)
    print(f"panel rows={len(df)}", flush=True)
    y = df["label"]

    factors = []
    for n in names:
        ric = daily_rank_ic(df[n], y)
        agg = aggregate(ric)
        rob = robust_all_regimes(agg)
        factors.append({"name": n, "family": _family(n), "expr": FACTOR_LIBRARY[n],
                        "in_frozen": n in frozen, "robust_all": rob, "agg": agg})
        marks = "".join(mark(agg["regimes"][k]["ic"]) if k in agg["regimes"] else "·"
                        for k, *_ in REGIMES)
        print(f"  {n:14s} all={agg['overall']['ic']:+.4f}/{agg['overall']['ir']:+.2f} "
              f"r3y={agg['recent3y']['ic']:+.4f} [{marks}] {'★' if rob else ' '}"
              f"{' frozen' if n in frozen else ''}", flush=True)

    rep = {"as_of": end.date().isoformat(), "universe": args.universe, "horizon": horizon,
           "start": args.start, "qlib_dir": qlib_dir, "regimes": REGIMES, "skipped": skipped,
           "n_insts": len(insts), "n_robust_all": sum(f["robust_all"] for f in factors),
           "factors": factors}
    rep_dir = Path(qlib_dir).resolve().parent / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{end.date().isoformat()}_h{horizon}" + ("_smoke" if args.limit else "") + ("_wf" if args.end else "")
    (rep_dir / f"factor_regimes_{tag}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2))
    (rep_dir / f"factor_regimes_{tag}.md").write_text(render_md(rep))
    print(f"ROBUST_ALL {rep['n_robust_all']}/{len(factors)}\n"
          f"REPORT -> {rep_dir}/factor_regimes_{tag}.md\nFACTOR_REGIMES_DONE", flush=True)


if __name__ == "__main__":
    main()
