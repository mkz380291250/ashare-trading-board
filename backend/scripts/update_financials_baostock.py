"""财务续接:用 baostock 季报把营收/归母净利追加进 tushare_extra.db 的 ts_income。

用法:
  python scripts/update_financials_baostock.py            # 全部在市 A 股(当日有行情的票)
  python scripts/update_financials_baostock.py --limit 50 # 冒烟
  python scripts/update_financials_baostock.py --n 4      # 往前多查几个报告期(补历史用)
注意:baostock 同 IP 单会话,别在夜链跑的时候另开(会把对方踢成"用户未登录")。
全市场 ~5500 只、每票 1~2 次查询、0.2~0.5s/次 → 报告季约 20~40 分钟,非报告季只查"缺失期"
(库里已有则不查),几分钟。
"""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, func, select
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote
from app.data.financials_update import update_financials, baostock_fetch_fn


def listed_codes(session) -> list[str]:
    last = session.scalar(select(func.max(DailyQuote.trade_date)))
    return sorted(session.scalars(
        select(distinct(DailyQuote.code)).where(DailyQuote.trade_date == last)).all())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="./data/tushare_extra.db")
    p.add_argument("--n", type=int, default=2, help="每票检查最近 N 个可能已披露的报告期")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--codes", default="", help="逗号分隔指定票(调试)")
    args = p.parse_args()

    if args.codes:
        codes = [c for c in args.codes.split(",") if c]
    else:
        session = make_session_factory(make_engine())()
        codes = listed_codes(session)
    if args.limit:
        codes = codes[: args.limit]
    fetch, src = baostock_fetch_fn()
    t0 = time.time()
    print(f"financials: {len(codes)} codes, n={args.n}, today={date.today()}", flush=True)
    try:
        stats = update_financials(args.db, codes, fetch_fn=fetch, n=args.n,
                                  log=lambda m: print(m, flush=True))
    finally:
        src.close()
    print(f"FINANCIALS_DONE {stats} in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
