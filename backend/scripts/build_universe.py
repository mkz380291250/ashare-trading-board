"""构建可投资域 instruments 文件(全市场去 ST / 次新)。

用法:python scripts/build_universe.py [--min-list-days 120] [--name investable]
产出:<qlib_data_dir>/instruments/<name>.txt
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.backtest.symbols import from_qlib_symbol
from app.quant.universe import filter_investable, write_instruments


def fetch_basic(token: str = ""):
    """baostock stock_basic -> [(ts_code, name, list_date: date)]。"""
    from app.data.baostock_source import stock_basic
    return stock_basic()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--min-list-days", type=int, default=120)
    p.add_argument("--name", default="investable")
    p.add_argument("--qlib-dir", default="",
                   help="缺省 settings.qlib_data_dir;研究库传 data/qlib_cn_full")
    p.add_argument("--dynamic", action="store_true",
                   help="按票动态起止(上市满 N 天起、退市前一日止),含已退市股;"
                        "基础信息读 tushare_extra.db")
    p.add_argument("--prefix", default="300,301",
                   help="--dynamic 时的代码前缀过滤,空=全市场")
    p.add_argument("--extra-db", default="./data/tushare_extra.db")
    p.add_argument("--index", default="",
                   help="按 ts_index_weight 月度成分做动态池,如 000300.SH / 000905.SH / 000852.SH")
    args = p.parse_args()

    s = get_settings()
    qlib_dir = Path(args.qlib_dir or s.qlib_data_dir)
    # 日期范围取自 qlib 日历;已有行情的票取自 all.txt(避免扫 405 万行库)
    cal = qlib_dir / "calendars" / "day.txt"
    days = cal.read_text().split()
    start = datetime.strptime(days[0], "%Y-%m-%d").date()
    end = datetime.strptime(days[-1], "%Y-%m-%d").date()
    all_txt = (qlib_dir / "instruments" / "all.txt").read_text().splitlines()
    in_db = {from_qlib_symbol(ln.split("\t")[0]) for ln in all_txt if ln.strip()}
    path = qlib_dir / "instruments" / f"{args.name}.txt"

    if args.index:
        from app.quant.universe import (index_member_rows, index_snapshots_from_extra_db,
                                        write_instrument_rows)
        snaps = index_snapshots_from_extra_db(args.extra_db, args.index)
        rows3 = [r for r in index_member_rows(snaps, cal_end=end)
                 if r[0] in in_db and r[2] >= start]
        rows3 = [(c, max(s_, start), e) for c, s_, e in rows3]
        n = write_instrument_rows(rows3, path)
        print(f"UNIVERSE_DONE name={args.name} index={args.index} snapshots={len(snaps)} "
              f"rows={n} codes={len({c for c, _, _ in rows3})} -> {path}", flush=True)
        return

    if args.dynamic:
        from app.quant.universe import dynamic_rows, write_instrument_rows, basic_from_extra_db
        rows = basic_from_extra_db(args.extra_db)
        prefixes = tuple(x for x in args.prefix.split(",") if x)
        rows3 = [r for r in dynamic_rows(rows, cal_start=start, cal_end=end,
                                         min_list_days=args.min_list_days, prefixes=prefixes)
                 if r[0] in in_db]
        n = write_instrument_rows(rows3, path)
        print(f"UNIVERSE_DONE name={args.name} dynamic in={len(rows)} kept={n} -> {path}",
              flush=True)
        return

    rows = fetch_basic(s.tushare_token)
    investable = filter_investable(rows, as_of=end,
                                   min_list_days=args.min_list_days)
    # 只保留 qlib 库里确有行情的票
    codes = [c for c in investable if c in in_db]
    n = write_instruments(codes, str(path), start=start, end=end)
    print(f"UNIVERSE_DONE name={args.name} in={len(rows)} "
          f"investable={len(investable)} with_quotes={n} -> {path}", flush=True)


if __name__ == "__main__":
    main()
