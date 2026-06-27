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
from app.research.store import ResearchStore
from app.research.signal import ResearchSignalProvider


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None, help="YYYY-MM-DD; default = latest in DB")
    p.add_argument("--window", type=int, default=20)
    p.add_argument("--source", choices=["qlib", "momentum"], default="qlib")
    p.add_argument("--top-n", type=int, default=8, help="仅影响打印,落库为全量")
    p.add_argument("--with-research", action="store_true",
                   help="(momentum 源)挂入研报质化信号")
    return p


def main():
    args = build_parser().parse_args()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    as_of = (date(*map(int, args.date.split("-"))) if args.date
             else store.trading_dates(date.today(), 1)[0])

    if args.source == "qlib":
        from app.config import get_settings
        from app.backtest.qlib_data import init_qlib
        from app.factors.frozen import load_frozen
        from app.discovery.qlib_provider import run_qlib_discovery
        from scripts.freeze_factors import frozen_path
        s = get_settings()
        init_qlib(s.qlib_data_dir)
        from qlib.data import D
        frozen = load_frozen(frozen_path(s))
        insts = D.list_instruments(D.instruments(frozen.universe), as_list=True)
        picks = run_qlib_discovery(session, as_of, frozen, insts)
        print(f"[qlib] {as_of} 全市场 {len(insts)} 只打分,落 {len(picks)} 条;Top{args.top_n}:")
        for code, score in picks[:args.top_n]:
            print(f"  {code}  {score:+.4f}")
        return

    # momentum 源:原有逻辑保留
    providers = [MomentumProvider()]
    if args.with_research:
        providers.append(ResearchSignalProvider(ResearchStore(session)))
    runner = DiscoveryRunner(session, QuoteStoreMarketHistory(store),
                             providers, DiscoveryScorer(top_n=args.top_n),
                             window=args.window)
    picks = runner.run(as_of)
    for code, score, raw in picks:
        print(f"{code}  score={score:.3f}  {raw}", flush=True)
    print(f"DISCOVERY_DONE as_of={as_of} picks={len(picks)}", flush=True)


if __name__ == "__main__":
    main()
