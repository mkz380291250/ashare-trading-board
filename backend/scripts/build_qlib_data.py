import argparse, sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, func, select
from app.config import get_settings
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote
from app.backtest.qlib_data import (export_market_csvs_full, export_market_csvs_bulk,
                                    export_csi300_csv, build_bin)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv-dir", default="./data/qlib_csv")
    p.add_argument("--qlib-dir", default="./data/qlib_cn")
    p.add_argument("--limit", type=int, default=0, help=">0 则只导前 N 只(冒烟用)")
    p.add_argument("--start", default="",
                   help="覆盖 settings.qlib_export_start(研究库用 2010-01-01)")
    p.add_argument("--extra", action="store_true",
                   help="附加 PIT 财务/分红/资金流字段(读 data/tushare_extra.db)")
    p.add_argument("--extra-db", default="./data/tushare_extra.db")
    p.add_argument("--no-moneyflow", action="store_true",
                   help="--extra 时跳过资金流表(夜链用;资金流只做研究且冷读极慢)")
    p.add_argument("--bulk", action="store_true",
                   help="顺序扫全表再分组导出(研究库全导用;--start 给了默认开)")
    args = p.parse_args()

    s = get_settings()
    engine = make_engine()
    session = make_session_factory(engine)()
    start = session.scalar(select(func.min(DailyQuote.trade_date)))
    end = session.scalar(select(func.max(DailyQuote.trade_date)))
    export_start = date.fromisoformat(args.start or s.qlib_export_start)
    if start < export_start:
        start = export_start
    extra_fn = None
    pit = None
    if args.extra:
        from app.quant.pit_fields import PitFields
        pit = PitFields(args.extra_db, moneyflow=not args.no_moneyflow)
        extra_fn = pit.for_code
    bulk = args.bulk or bool(args.start)
    if bulk:
        db_path = engine.url.database
        codes = None
        if args.limit:
            codes = sorted(session.scalars(
                select(distinct(DailyQuote.code)).where(DailyQuote.trade_date == end)).all())[: args.limit]
        print(f"exporting (bulk) {start}..{end} extra={args.extra} limit={args.limit}", flush=True)
        n = export_market_csvs_bulk(db_path, start, end, args.csv_dir, extra_fn=extra_fn, codes=codes)
    else:
        codes = sorted({c for c in session.scalars(select(distinct(DailyQuote.code))).all()})
        if args.limit:
            codes = codes[: args.limit]
        print(f"exporting {len(codes)} stocks {start}..{end} extra={args.extra}", flush=True)
        n = export_market_csvs_full(session, codes, start, end, args.csv_dir, extra_fn=extra_fn)
    if pit is not None:
        print(f"pit: {pit.missing} codes without financials", flush=True)
    from app.data.baostock_source import BaostockSource
    src = BaostockSource()
    csi = export_csi300_csv(src, start, end, args.csv_dir)
    src.close()
    print(f"exported {n} stocks + csi300={csi is not None}; dumping bin...", flush=True)
    build_bin(args.csv_dir, args.qlib_dir)
    print("QLIB_DUMP_DONE", flush=True)


if __name__ == "__main__":
    main()
