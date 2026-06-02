"""Incremental: fetch latest trading day bars, append CSVs, then mark-to-market.
Mark-to-market is invoked from the broker (Task 13) once accounts exist."""
import argparse
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.config import get_settings
from app.data.tushare_source import TushareSource
from app.data.qlib_store import write_instrument_csv


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--codes", nargs="+", required=True)
    p.add_argument("--days", type=int, default=5)
    args = p.parse_args()
    s = get_settings()
    src = TushareSource(token=s.tushare_token)
    end = date.today(); start = end - timedelta(days=args.days)
    for code in args.codes:
        bars = src.get_daily_bars(code, start, end)
        if bars:
            write_instrument_csv(bars, f"{s.qlib_data_dir}/csv_incr")
            print(f"{code}: {len(bars)} recent bars")


if __name__ == "__main__":
    main()
