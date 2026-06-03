import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, func
from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import Position, DiscoveryPick, WatchPoolEntry
from app.data.quote_store import QuoteStore
from app.data.rate_limiter import RateLimiter
from app.decision.llm import LocalClaudeClient, DeepSeekClient
from app.research.sources import (TushareResearchSource, EastMoneyNewsSource,
                                  CompositeSource)
from app.research.analyzer import ResearchAnalyzer
from app.research.store import ResearchStore
from app.research.runner import ResearchRunner


def _llm(s):
    if s.research_llm == "deepseek":
        return DeepSeekClient(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    return LocalClaudeClient(bin_path=s.claude_bin)


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]

    holds = {p.code for p in session.scalars(select(Position)).all()}
    top_date = session.scalar(select(func.max(DiscoveryPick.as_of)))
    top = {r.code for r in session.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == top_date)).all()} \
        if top_date else set()
    watch = {w.code for w in session.scalars(select(WatchPoolEntry)).all()}
    universe = holds | top | watch

    import tushare as ts
    pro = ts.pro_api(s.tushare_token)
    limiter = RateLimiter(max_calls=s.research_max_per_min, period_s=60.0)
    source = CompositeSource([
        TushareResearchSource(pro, limiter=limiter),
        EastMoneyNewsSource(),
    ])
    runner = ResearchRunner(source, ResearchAnalyzer(_llm(s)), ResearchStore(session))
    n = runner.run(universe, as_of)
    print(f"RESEARCH_DONE as_of={as_of} universe={len(universe)} written={n}",
          flush=True)


if __name__ == "__main__":
    main()
