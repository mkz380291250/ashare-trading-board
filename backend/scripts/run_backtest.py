import argparse, sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, select
from app.config import get_settings
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote
from app.data.quote_store import QuoteStore
from app.discovery.snapshot import QuoteStoreMarketHistory
from app.discovery.providers import MomentumProvider
from app.discovery.scorer import DiscoveryScorer
from app.backtest.qlib_data import init_qlib
from app.backtest.scores import build_score_frame
from app.backtest.factor import build_forward_returns, factor_report
from app.backtest.strategy import run_strategy_backtest
from app.backtest.symbols import to_qlib_symbol, from_qlib_symbol


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qlib-dir", default="./data/qlib_cn")
    p.add_argument("--window", type=int, default=20)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    args = p.parse_args()

    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    hist = QuoteStoreMarketHistory(store)
    prov = MomentumProvider()
    scorer = DiscoveryScorer(top_n=8)

    all_dates = sorted(session.scalars(select(distinct(DailyQuote.trade_date))).all())
    start = date(*map(int, args.start.split("-"))) if args.start else all_dates[args.window]
    end = date(*map(int, args.end.split("-"))) if args.end else all_dates[-1]
    dates = [d for d in all_dates if start <= d <= end]

    def factor_fn(d):
        snap = hist.load(d, args.window)
        return prov.compute(snap) if snap else {}

    score = build_score_frame(dates, factor_fn, scorer)
    print(f"score frame: {len(score)} rows over {len(dates)} days", flush=True)

    bars_cache = {}
    def adj_close_fn(d, sym):
        code = from_qlib_symbol(sym)
        if code not in bars_cache:
            bars_cache[code] = {b.trade_date: b.close * b.adj_factor
                                for b in store.get_bars(code, start, end)}
        return bars_cache[code].get(d)

    codes_syms = sorted(set(score.index.get_level_values("instrument")))
    fwd = build_forward_returns(dates, codes_syms, adj_close_fn)
    rep = factor_report(score, fwd)
    print("FACTOR:", rep, flush=True)

    init_qlib(args.qlib_dir)
    bt = run_strategy_backtest(score, start=start, end=end)
    print("STRATEGY:", bt, flush=True)
    print("BACKTEST_DONE", flush=True)


if __name__ == "__main__":
    main()
