import argparse, sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, select
from app.config import get_settings
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote
from app.backtest.qlib_data import (export_market_csvs_full, export_csi300_csv, build_bin)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv-dir", default="./data/qlib_csv")
    p.add_argument("--qlib-dir", default="./data/qlib_cn")
    p.add_argument("--limit", type=int, default=0, help=">0 则只导前 N 只(冒烟用)")
    args = p.parse_args()

    s = get_settings()
    session = make_session_factory(make_engine())()
    dates = sorted(session.scalars(select(distinct(DailyQuote.trade_date))).all())
    start, end = dates[0], dates[-1]
    export_start = date.fromisoformat(s.qlib_export_start)
    if start < export_start:
        start = export_start
    codes = sorted({c for c in session.scalars(select(distinct(DailyQuote.code))).all()})
    if args.limit:
        codes = codes[: args.limit]
    print(f"exporting {len(codes)} stocks {start}..{end}", flush=True)
    n = export_market_csvs_full(session, codes, start, end, args.csv_dir)
    from app.data.baostock_source import BaostockSource
    src = BaostockSource()
    csi = export_csi300_csv(src, start, end, args.csv_dir)
    src.close()
    print(f"exported {n} stocks + csi300={csi is not None}; dumping bin...", flush=True)
    build_bin(args.csv_dir, args.qlib_dir)
    print("QLIB_DUMP_DONE", flush=True)


if __name__ == "__main__":
    main()
