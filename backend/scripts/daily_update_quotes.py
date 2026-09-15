"""增量拉全市场日线到 daily_quotes(2026-09 起数据源 baostock + 东财北交所,
替代到期的 tushare)。按 baostock 交易日历找未入库的日期,逐只股票拉窗口,
一天有数据才 mark_ingested(baostock 当日数据约 18:00 后才有,盘中跑不会误标)。"""
import argparse
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.baostock_source import BaostockSource
from app.data.baostock_market import BaostockMarketFetcher, load_refs, listed_a_shares
from app.data.quote_store import QuoteStore


def update(session, start: date, end: date, log=print, use_baostock: bool | None = None,
           ) -> list[date]:
    store = QuoteStore(session)
    cal = BaostockSource()
    try:
        days = cal.trading_days(start, end)
    except Exception as exc:                    # noqa: BLE001 — baostock 挂了退化成工作日历
        log(f"CALENDAR_FALLBACK weekdays: {exc!r}", flush=True)
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)
                if (start + timedelta(days=i)).weekday() < 5]
    done = store.ingested_dates()
    todo = [d for d in days if d not in done]
    if not todo:
        log("UPDATE_DONE nothing to do", flush=True)
        return []
    refs = load_refs(session)
    last_open = max(d for d in days if d <= date.today()) if days else end
    try:
        listed = listed_a_shares(cal, last_open)
    except Exception as exc:                    # noqa: BLE001 — 拿不到新股名单不挡更新
        log(f"LISTED_SKIP {exc!r}", flush=True)
        listed = []
    try:
        cal.close()
    except Exception:                           # noqa: BLE001
        pass
    codes = sorted(set(refs) | set(listed))
    log(f"todo={todo} codes={len(codes)} (库内 {len(refs)}, 新增 {len(set(listed) - set(refs))})",
        flush=True)
    if use_baostock is None:
        use_baostock = get_settings().quotes_source == "baostock"
    fetched = BaostockMarketFetcher(log=log, use_baostock=use_baostock).fetch(
        codes, refs, start=min(todo), end=end, trading_days=days)
    written = []
    for d in todo:
        rows = fetched.get(d, [])
        if not rows:
            log(f"{d}: no data yet", flush=True)
            continue
        store.upsert_day(d, rows); store.mark_ingested(d)
        written.append(d)
        log(f"{d}: {len(rows)} rows", flush=True)
    log("UPDATE_DONE", flush=True)
    return written


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)  # look-back window
    p.add_argument("--source", choices=["baostock", "tencent"], default=None,
                   help="默认读 settings.quotes_source;tencent=跳过 baostock 全走腾讯")
    args = p.parse_args()
    engine = make_engine()
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    end = date.today(); start = end - timedelta(days=args.days)
    update(session, start, end,
           use_baostock=None if args.source is None else args.source == "baostock")


if __name__ == "__main__":
    main()
