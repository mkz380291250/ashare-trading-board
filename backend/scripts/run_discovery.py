import argparse
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.quote_store import QuoteStore
from app.discovery.snapshot import QuoteStoreMarketHistory
from app.discovery.providers import MomentumProvider
from app.discovery.scorer import DiscoveryScorer
from app.discovery.runner import DiscoveryRunner


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None, help="YYYY-MM-DD; default = latest in DB")
    p.add_argument("--window", type=int, default=20)
    args = p.parse_args()

    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)

    as_of = (date(*map(int, args.date.split("-"))) if args.date
             else store.trading_dates(date.today(), 1)[0])
    runner = DiscoveryRunner(session, QuoteStoreMarketHistory(store),
                             [MomentumProvider()], DiscoveryScorer(top_n=8),
                             window=args.window)
    picks = runner.run(as_of)
    for code, score, raw in picks:
        print(f"{code}  score={score:.3f}  {raw}", flush=True)
    print(f"DISCOVERY_DONE as_of={as_of} picks={len(picks)}", flush=True)


if __name__ == "__main__":
    main()
