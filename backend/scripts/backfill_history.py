import argparse
from datetime import date
from app.config import get_settings
from app.data.tushare_source import TushareSource
from app.data.qlib_store import write_instrument_csv


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--codes", nargs="+", required=True)
    p.add_argument("--start", default="20180101")
    p.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    args = p.parse_args()
    s = get_settings()
    src = TushareSource(token=s.tushare_token)

    def _d(x):
        return date(int(x[:4]), int(x[4:6]), int(x[6:8]))

    for code in args.codes:
        bars = src.get_daily_bars(code, _d(args.start), _d(args.end))
        path = write_instrument_csv(bars, f"{s.qlib_data_dir}/csv")
        print(f"{code}: {len(bars)} bars -> {path}")


if __name__ == "__main__":
    main()
