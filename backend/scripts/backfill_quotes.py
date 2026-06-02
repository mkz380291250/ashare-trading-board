import argparse
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.rate_limiter import RateLimiter
from app.data.market_fetch import MarketFetcher
from app.data.quote_store import QuoteStore


def _d(x: str) -> date:
    return date(int(x[:4]), int(x[4:6]), int(x[6:8]))


def trading_days(pro, limiter, start: str, end: str) -> list[date]:
    limiter.acquire()
    cal = pro.trade_cal(start_date=start, end_date=end)
    open_days = cal[cal["is_open"] == 1]["cal_date"].tolist()
    return sorted(_d(str(x)) for x in open_days)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="20210101")
    p.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    p.add_argument("--max-per-min", type=int, default=100)
    args = p.parse_args()

    s = get_settings()
    import tushare as ts
    ts.set_token(s.tushare_token)
    pro = ts.pro_api()

    engine = make_engine()
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    limiter = RateLimiter(max_calls=args.max_per_min, period_s=60.0)
    fetcher = MarketFetcher(pro=pro, limiter=limiter)

    days = trading_days(pro, limiter, args.start, args.end)
    done = store.ingested_dates()
    todo = [d for d in days if d not in done]
    print(f"calendar={len(days)} done={len(done)} todo={len(todo)}", flush=True)

    for i, d in enumerate(todo, 1):
        try:
            rows = fetcher.fetch_day(d)
            store.upsert_day(d, rows)
            store.mark_ingested(d)
            print(f"[{i}/{len(todo)}] {d}: {len(rows)} rows", flush=True)
        except Exception as e:  # leave day un-ingested -> retried next run
            print(f"[{i}/{len(todo)}] {d}: ERROR {e!r} (will retry next run)", flush=True)
    print("BACKFILL_DONE", flush=True)


if __name__ == "__main__":
    main()
