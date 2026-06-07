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


def fetch_basic(token: str):
    """tushare stock_basic -> [(ts_code, name, list_date: date)]。"""
    import tushare as ts
    pro = ts.pro_api(token)
    df = pro.stock_basic(exchange="", list_status="L",
                         fields="ts_code,name,list_date")
    out = []
    for r in df.itertuples(index=False):
        try:
            ld = datetime.strptime(str(r.list_date), "%Y%m%d").date()
        except (ValueError, TypeError):
            ld = None
        out.append((r.ts_code, r.name, ld))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--min-list-days", type=int, default=120)
    p.add_argument("--name", default="investable")
    args = p.parse_args()

    s = get_settings()
    qlib_dir = Path(s.qlib_data_dir)
    # 日期范围取自 qlib 日历;已有行情的票取自 all.txt(避免扫 405 万行库)
    cal = qlib_dir / "calendars" / "day.txt"
    days = cal.read_text().split()
    start = datetime.strptime(days[0], "%Y-%m-%d").date()
    end = datetime.strptime(days[-1], "%Y-%m-%d").date()
    all_txt = (qlib_dir / "instruments" / "all.txt").read_text().splitlines()
    in_db = {from_qlib_symbol(ln.split("\t")[0]) for ln in all_txt if ln.strip()}

    rows = fetch_basic(s.tushare_token)
    investable = filter_investable(rows, as_of=end,
                                   min_list_days=args.min_list_days)
    # 只保留 qlib 库里确有行情的票
    codes = [c for c in investable if c in in_db]

    path = qlib_dir / "instruments" / f"{args.name}.txt"
    n = write_instruments(codes, str(path), start=start, end=end)
    print(f"UNIVERSE_DONE name={args.name} in={len(rows)} "
          f"investable={len(investable)} with_quotes={n} -> {path}", flush=True)


if __name__ == "__main__":
    main()
