import argparse
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.rate_limiter import RateLimiter
from app.data.market_fetch import MarketFetcher
from app.data.quote_store import QuoteStore
from scripts.backfill_quotes import trading_days


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)  # look-back window
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

    end = date.today(); start = end - timedelta(days=args.days)
    days = trading_days(pro, limiter, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    done = store.ingested_dates()
    for d in [x for x in days if x not in done]:
        rows = fetcher.fetch_day(d)
        store.upsert_day(d, rows); store.mark_ingested(d)
        print(f"{d}: {len(rows)} rows", flush=True)
    print("UPDATE_DONE", flush=True)


if __name__ == "__main__":
    main()
