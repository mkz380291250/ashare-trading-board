import argparse, sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, select
from app.config import get_settings
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote
from app.data.quote_store import QuoteStore
from app.backtest.qlib_data import (export_market_csvs, export_csi300_csv, build_bin)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv-dir", default="./data/qlib_csv")
    p.add_argument("--qlib-dir", default="./data/qlib_cn")
    p.add_argument("--limit", type=int, default=0, help=">0 则只导前 N 只(冒烟用)")
    args = p.parse_args()

    s = get_settings()
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    dates = sorted(session.scalars(select(distinct(DailyQuote.trade_date))).all())
    start, end = dates[0], dates[-1]
    codes = sorted({c for c in session.scalars(select(distinct(DailyQuote.code))).all()})
    if args.limit:
        codes = codes[: args.limit]
    print(f"exporting {len(codes)} stocks {start}..{end}", flush=True)
    n = export_market_csvs(store, codes, start, end, args.csv_dir)
    import tushare as ts
    pro = ts.pro_api(s.tushare_token)
    csi = export_csi300_csv(pro, start, end, args.csv_dir)
    print(f"exported {n} stocks + csi300={csi is not None}; dumping bin...", flush=True)
    build_bin(args.csv_dir, args.qlib_dir)
    print("QLIB_DUMP_DONE", flush=True)


if __name__ == "__main__":
    main()
